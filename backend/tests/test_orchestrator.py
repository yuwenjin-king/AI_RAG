"""检索编排端到端（sqlite + 本地 BM25 兜底 + 父子 Small-to-Big 回溯）。"""
import pytest

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.services.retrieval import orchestrator


@pytest.mark.asyncio
async def test_retrieve_parent_child_context_expansion(sqlite_session):
    s = sqlite_session
    doc = Document(
        tenant_id="A", title="Manual", object_key="k",
        content_type="text/plain", status="indexed",
    )
    s.add(doc)
    await s.flush()

    # 父块：不含查询词（仅作上下文）
    parent = Chunk(
        tenant_id="A", document_id=doc.id, ordinal=0,
        content="The widget assembly procedure is detailed in section four.",
        parent_chunk_id=None,
    )
    s.add(parent)
    await s.flush()
    # 子块：含查询词，精确溯源到第 3 页某区域
    child = Chunk(
        tenant_id="A", document_id=doc.id, ordinal=1,
        content="connect using the blue cable to the power module",
        page_no=3, bbox=[0.1, 0.1, 0.3, 0.3], parent_chunk_id=parent.id,
    )
    s.add(child)
    await s.commit()

    res = await orchestrator.retrieve(s, TenantContext("A"), "blue cable")

    assert res.chunks, "本地 BM25 应召回子块"
    top = res.chunks[0]
    assert top.parent_chunk_id == parent.id
    # Small-to-Big：生成上下文回溯到父块（父块不含查询词，证明是回溯而非子块自身）
    assert "widget assembly" in top.context
    # 引用仍精确到子块页码/bbox
    assert top.page_no == 3 and top.bbox == [0.1, 0.1, 0.3, 0.3]
    # 无 Milvus/OpenSearch → 必然降级
    assert any("vector" in d or "keyword" in d for d in res.degraded)


@pytest.mark.asyncio
async def test_retrieve_rerank_final_topk_truncates(sqlite_session, monkeypatch):
    """rerank_final_topk 截断：返回 chunk 数 ≤ 该值（提引用精度、省上下文）。

    NoOp reranker（测试无配置）下按 RRF 序截断，验证截断逻辑本身与 reranker 解耦。
    """
    monkeypatch.setattr(orchestrator.settings, "rerank_final_topk", 2)
    monkeypatch.setattr(orchestrator.settings, "query_rewrite_enabled", False)
    monkeypatch.setattr(orchestrator.settings, "query_expansion_enabled", False)
    s = sqlite_session
    doc = Document(tenant_id="A", title="Manual", object_key="k",
                   content_type="text/plain", status="indexed")
    s.add(doc)
    await s.flush()
    # 多个含查询词的 chunk → BM25 召回多个（>2 才能验证截断）
    for i in range(6):
        s.add(Chunk(tenant_id="A", document_id=doc.id, ordinal=i,
                    content=f"blue cable power module variant {i}", parent_chunk_id=None))
    await s.commit()

    res = await orchestrator.retrieve(s, TenantContext("A"), "blue cable")
    assert res.chunks, "应召回"
    assert len(res.chunks) <= 2, f"rerank_final_topk=2 应截断，实得 {len(res.chunks)}"
