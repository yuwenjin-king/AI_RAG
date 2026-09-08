"""Kafka at-least-once 消费 + ingest 重驱动幂等测试（sqlite + 假 aiokafka）。

背景：旧版 consume enable_auto_commit=True 是 at-most-once（worker 崩溃丢在途
消息、doc 卡中途状态无人认领）。此处锁定两个不变式：
1) offset 在 on_message 成功后才 commit；处理失败不 commit；
2) process_pending 覆盖中途状态（parsing/chunking/embedding）；
3) process_document 重驱动先清半成品 chunks（幂等）。
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from sqlalchemy import select

from app.core.config import settings as cfg
from app.db.models import Chunk, Document
from app.infra import kafka_bus
from app.services import ingest as ingest_mod


# ===== 假 aiokafka：记录 commit 时序 =====

class _FakeMsg:
    def __init__(self, value: dict):
        self.value = value


class _FakeConsumer:
    def __init__(self, messages: list):
        self._messages = messages
        self.commits = 0
        self.stopped = False
        self.auto_commit: bool | None = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        self.commits += 1

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            # 消息耗尽：以 CancelledError 结束 consume（等价 worker 关停时的 task cancel）
            raise asyncio.CancelledError


def _install_fake_aiokafka(monkeypatch, consumer: _FakeConsumer) -> None:
    fake = types.ModuleType("aiokafka")

    def factory(*args, **kwargs):
        consumer.auto_commit = kwargs.get("enable_auto_commit")
        return consumer

    fake.AIOKafkaConsumer = factory
    monkeypatch.setitem(sys.modules, "aiokafka", fake)


@pytest.mark.asyncio
async def test_consume_commits_only_after_handler(monkeypatch):
    consumer = _FakeConsumer([_FakeMsg({"doc_id": 1}), _FakeMsg({"doc_id": 2})])
    _install_fake_aiokafka(monkeypatch, consumer)

    processed: list[int] = []
    commits_at_handle: list[tuple[int, int]] = []  # (已处理条数, 当时 commit 数)

    async def on_message(value: dict) -> None:
        processed.append(value["doc_id"])
        commits_at_handle.append((len(processed), consumer.commits))

    with pytest.raises(asyncio.CancelledError):
        await kafka_bus.consume("t", "g", on_message=on_message)

    assert processed == [1, 2]
    assert consumer.auto_commit is False          # 关掉 auto-commit 才可能 at-least-once
    assert consumer.commits == 2                  # 每条成功处理各 commit 一次
    # 每次进入 handler 时，此前 commit 数 == 已处理数 - 1（commit 严格在处理之后）
    assert all(n - 1 == c for n, c in commits_at_handle)
    assert consumer.stopped                       # 退出路径释放消费者


@pytest.mark.asyncio
async def test_consume_no_commit_on_handler_error(monkeypatch):
    consumer = _FakeConsumer([_FakeMsg({"doc_id": 1}), _FakeMsg({"doc_id": 2})])
    _install_fake_aiokafka(monkeypatch, consumer)

    async def on_message(value: dict) -> None:
        if value["doc_id"] == 1:
            raise RuntimeError("boom")            # 处理失败 → 不 commit，重启后重投

    with pytest.raises(asyncio.CancelledError):
        await kafka_bus.consume("t", "g", on_message=on_message)

    assert consumer.commits == 1                  # 只有第二条成功后提交


# ===== process_pending：中途状态覆盖 =====

@pytest.mark.asyncio
async def test_process_pending_redrives_mid_pipeline(sqlite_session, monkeypatch):
    called: list[int] = []

    async def fake_process(session, doc_id: int) -> None:
        called.append(doc_id)

    monkeypatch.setattr(ingest_mod, "process_document", fake_process)

    statuses = ["pending", "parsing", "chunking", "embedding", "failed", "indexed", "layout_pending"]
    for i, st in enumerate(statuses, start=1):
        sqlite_session.add(Document(
            id=i, tenant_id="t", knowledge_base_id=1,
            title=f"d{i}", object_key=f"k{i}", status=st,
        ))
    await sqlite_session.commit()

    n = await ingest_mod.process_pending(sqlite_session)

    assert n == 5
    assert called == [1, 2, 3, 4, 5]              # indexed/layout_pending 不动


# ===== process_document：重驱动 purge 幂等 =====

def _make_doc_with_stale_chunks(session) -> None:
    session.add(Document(
        id=9, tenant_id="t", knowledge_base_id=1,
        title="stale.pdf", object_key="k/9.pdf", status="embedding",
    ))
    session.add(Chunk(id=101, tenant_id="t", document_id=9, ordinal=0, content="half"))
    session.add(Chunk(id=102, tenant_id="t", document_id=9, ordinal=1, content="done"))


def _stub_pipeline(monkeypatch, purged: list, indexed: list) -> None:
    """桩掉对象存储/解析/索引；记录 milvus+os 的 delete_by_doc 调用。"""

    async def fake_del(tenant, doc_id: int) -> None:
        purged.append(doc_id)

    monkeypatch.setattr(ingest_mod.milvus_store, "delete_by_doc", fake_del)
    monkeypatch.setattr(ingest_mod.opensearch_store, "delete_by_doc", fake_del)
    monkeypatch.setattr(
        ingest_mod.object_storage, "get_object_bytes", lambda key: b"payload"
    )

    from app.services.knowledge.block import Block, ParsedDoc
    parsed = ParsedDoc(title="t", blocks=[Block(text="hello world " * 20)])
    monkeypatch.setattr(ingest_mod.parser, "parse", lambda *a, **kw: parsed)

    async def fake_index(session, doc, tenant, blocks) -> None:
        indexed.append(doc.id)

    monkeypatch.setattr(ingest_mod, "_index_blocks", fake_index)
    monkeypatch.setattr(cfg, "vision_enabled", False)
    monkeypatch.setattr(cfg, "graph_enabled", False)


@pytest.mark.asyncio
async def test_process_document_purges_stale_chunks_on_redrive(sqlite_session, monkeypatch):
    _make_doc_with_stale_chunks(sqlite_session)
    await sqlite_session.commit()

    purged: list[int] = []
    indexed: list[int] = []
    _stub_pipeline(monkeypatch, purged, indexed)

    await ingest_mod.process_document(sqlite_session, 9)

    assert purged == [9, 9]                       # milvus + opensearch 各一次
    assert indexed == [9]                         # 清完重建
    remaining = (await sqlite_session.execute(
        select(Chunk).where(Chunk.document_id == 9)
    )).scalars().all()
    assert remaining == []                        # 半成品 PG chunks 已清（真实删除）


@pytest.mark.asyncio
async def test_process_document_fresh_doc_no_purge(sqlite_session, monkeypatch):
    sqlite_session.add(Document(
        id=10, tenant_id="t", knowledge_base_id=1,
        title="fresh.pdf", object_key="k/10.pdf", status="pending",
    ))
    await sqlite_session.commit()

    purged: list[int] = []
    indexed: list[int] = []
    _stub_pipeline(monkeypatch, purged, indexed)

    await ingest_mod.process_document(sqlite_session, 10)

    assert purged == []                           # 首次处理无残留，不触发清理
    assert indexed == [10]


# ===== opensearch purge：refresh 必须先于 delete_by_query =====
# 真实重驱动验证暴露：purge→reindex 亚秒内背靠背时，刚 bulk 未 refresh 的
# doc 对 delete_by_query 不可见 → 漏删成残留（同 doc 两轮 chunk 并存）。

@pytest.mark.asyncio
async def test_os_delete_by_doc_refreshes_first(monkeypatch):
    from app.core.tenant import TenantContext
    from app.infra import opensearch_store as os_store

    calls: list[str] = []

    class _FakeIndices:
        async def refresh(self, *, index: str) -> None:
            calls.append(f"refresh:{index}")

    class _FakeClient:
        indices = _FakeIndices()

        async def delete_by_query(self, *, index: str, body: dict) -> None:
            calls.append(f"delete_by_query:{index}:{body}")

    monkeypatch.setattr(os_store, "_available", True)
    monkeypatch.setattr(os_store, "_client", _FakeClient())

    await os_store.delete_by_doc(TenantContext(tenant_id="default"), 27)

    assert calls == [
        "refresh:rag-chunks-default",
        "delete_by_query:rag-chunks-default:{'query': {'term': {'doc_id': 27}}}",
    ]
