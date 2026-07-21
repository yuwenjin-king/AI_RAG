"""数据处理管线（设计书 §4.2 知识处理层 + §4.3 存储双写）。

由 ingest_worker（Kafka 消费）或上传 API（同步兜底）调用：
解析 → 分块 → embedding → 写 PG chunks → 双写 Milvus/OpenSearch → 更新状态
"""
from __future__ import annotations

import traceback
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import CHUNKS_INDEXED, INGEST_TOTAL, LAYOUT_PROCESSED
from app.core.tenant import TenantContext
from app.db.models import DocumentStatus
from app.infra import kafka_bus, object_storage, opensearch_store, milvus_store
from app.repositories import document as doc_repo
from app.services.ingestion import parser
from app.services.knowledge import chunker
from app.services.knowledge.block import ParsedDoc
from app.services.knowledge.embedding import get_provider

log = get_logger(__name__)


def _is_pdf(content_type: str, title: str = "") -> bool:
    ct = (content_type or "").lower()
    return ct == "application/pdf" or (title or "").lower().endswith(".pdf")


async def _enqueue_layout(doc_id: int) -> None:
    """入队视觉处理任务（layout_worker 消费 rag.layout）。Kafka 不可用则跳过（轮询兜底）。"""
    await kafka_bus.produce(settings.kafka_layout_topic, {"doc_id": doc_id}, key=str(doc_id))


async def _index_blocks(session, doc, tenant: TenantContext, blocks) -> None:
    """分块 → embedding → 双写索引（父子 Small-to-Big，仅子块入索引）。

    blocks: 带 page_no/bbox 的 Block 列表（来自文本层或视觉解析）。
    """
    doc_id = doc.id
    parsed = ParsedDoc(title=doc.title, blocks=blocks)
    await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.CHUNKING)
    if settings.chunk_parent_child:
        items = chunker.chunk_document_parent_child(
            parsed,
            parent_size=settings.chunk_parent_size,
            child_size=settings.chunk_child_size,
            overlap=settings.chunk_overlap,
        )
    else:
        items = [
            {**c, "level": "child", "parent_key": None}
            for c in chunker.chunk_document(
                parsed, max_size=settings.chunk_child_size, overlap=settings.chunk_overlap
            )
        ]
    child_items = [i for i in items if i["level"] == "child"]
    parent_items = [i for i in items if i["level"] == "parent"]
    if not child_items:
        raise ValueError("no extractable text")

    # 父块（仅 PG）
    parent_id_by_key: dict[int, int] = {}
    if parent_items:
        parent_dicts = [
            {
                "tenant_id": tenant.tenant_id, "document_id": doc_id, "ordinal": i["ordinal"],
                "content": i["content"], "page_no": i.get("page_no"), "bbox": i.get("bbox"),
                "parent_chunk_id": None, "extra": i.get("extra", {}), "vector_id": None,
            }
            for i in parent_items
        ]
        parent_objs = await doc_repo.add_chunks(session, parent_dicts)
        for k, obj in enumerate(parent_objs):
            parent_id_by_key[k + 1] = obj.id

    # 子块（参与索引）
    child_dicts = [
        {
            "tenant_id": tenant.tenant_id, "document_id": doc_id, "ordinal": i["ordinal"],
            "content": i["content"], "page_no": i.get("page_no"), "bbox": i.get("bbox"),
            "parent_chunk_id": parent_id_by_key.get(i.get("parent_key")) if i.get("parent_key") else None,
            "extra": i.get("extra", {}), "vector_id": None,
        }
        for i in child_items
    ]
    chunk_objs = await doc_repo.add_chunks(session, child_dicts)

    # embedding + 双写（仅子块）
    await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.EMBEDDING)
    from app.services.knowledge.embedding import embed_texts
    vectors = await embed_texts([c.content for c in chunk_objs])
    if len(vectors) != len(chunk_objs):
        vectors = (vectors + [vectors[-1]] * len(chunk_objs))[: len(chunk_objs)]

    milvus_records = []
    for idx, obj in enumerate(chunk_objs):
        milvus_records.append({
            "vector_id": str(obj.id), "embedding": vectors[idx], "tenant_id": tenant.tenant_id,
            "doc_id": doc_id, "chunk_id": obj.id, "kb_id": doc.knowledge_base_id or 0,
            "content": (obj.content or "")[:8192],
        })
        obj.vector_id = str(obj.id)
    await session.flush()
    upserted = await milvus_store.upsert(tenant, milvus_records)

    os_docs = [{
        "chunk_id": obj.id, "doc_id": doc_id, "tenant_id": tenant.tenant_id,
        "knowledge_base_id": doc.knowledge_base_id or 0, "title": doc.title,
        "content": obj.content, "page_no": obj.page_no, "bbox": obj.bbox, "tags": [],
    } for obj in chunk_objs]
    indexed = await opensearch_store.index_chunks(tenant, os_docs)

    meta_patch = {
        "pages": len({i.get("page_no") for i in items if i.get("page_no") is not None}) or None,
        "chunks": len(chunk_objs), "parent_chunks": len(parent_items),
        "milvus_upserted": upserted, "opensearch_indexed": indexed,
    }
    await doc_repo.set_status(
        session, tenant, doc_id, DocumentStatus.INDEXED,
        embedding_status="done", meta_patch=meta_patch,
    )
    INGEST_TOTAL.labels(tenant=tenant.tenant_id, status="indexed").inc()
    CHUNKS_INDEXED.labels(tenant=tenant.tenant_id).inc(len(chunk_objs))
    log.info(
        "index.done doc_id=%s tenant=%s children=%s parents=%s milvus=%s os=%s",
        doc_id, tenant.tenant_id, len(chunk_objs), len(parent_items), upserted, indexed,
    )


async def process_document(session: AsyncSession, doc_id: int) -> None:
    """文本路径：解析 → 文本层分块 → 索引；扫描件/复杂件入队视觉处理。"""
    from sqlalchemy import select
    from app.db.models import Document

    doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        log.warning("ingest.doc_not_found doc_id=%s", doc_id)
        return

    tenant = TenantContext(tenant_id=doc.tenant_id)
    try:
        await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.PARSING)
        data = object_storage.get_object_bytes(doc.object_key)
        parsed = parser.parse(data, doc.content_type, doc.title)
        doc.title = parsed.title or doc.title

        if parsed.blocks:
            await _index_blocks(session, doc, tenant, parsed.blocks)
            # 复杂/扫描件：已有文本层结果（降级可用），异步视觉补强 bbox/顺序
            if parsed.needs_vision and settings.vision_enabled:
                await _enqueue_layout(doc_id)
        elif settings.vision_enabled and _is_pdf(doc.content_type, doc.title):
            # 无文本层（扫描件）：交给 layout_worker 做 OCR
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.LAYOUT_PENDING, meta_patch={"queued_layout": True}
            )
            await _enqueue_layout(doc_id)
            log.info("ingest.layout_queued doc_id=%s (scanned, no text layer)", doc_id)
        else:
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.FAILED, error="no extractable text"
            )
    except Exception as e:  # noqa: BLE001
        INGEST_TOTAL.labels(tenant=tenant.tenant_id, status="failed").inc()
        log.error("ingest.failed doc_id=%s err=%s\n%s", doc_id, e, traceback.format_exc())
        try:
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.FAILED, error=f"{type(e).__name__}: {e}"
            )
        except Exception:  # noqa: BLE001
            pass


async def process_pending(session: AsyncSession, limit: int = 100) -> int:
    """扫描 status=pending 的文档并处理（兜底/重试入口）。"""
    from sqlalchemy import select
    from app.db.models import Document

    ids = (
        await session.execute(
            select(Document.id)
            .where(Document.status.in_([DocumentStatus.PENDING.value, DocumentStatus.FAILED.value]))
            .order_by(Document.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    for doc_id in ids:
        await process_document(session, int(doc_id))
    return len(ids)


async def process_layout(session: AsyncSession, doc_id: int) -> None:
    """视觉路径：版面检测 + 区域级 OCR → 清理旧索引 → 重新分块索引（扫描件/复杂件）。"""
    import asyncio

    from sqlalchemy import select
    from app.db.models import Document

    from app.services import vision

    doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        log.warning("layout.doc_not_found doc_id=%s", doc_id)
        return
    tenant = TenantContext(tenant_id=doc.tenant_id)
    try:
        data = object_storage.get_object_bytes(doc.object_key)
        blocks = await asyncio.to_thread(
            vision.extract_with_vision, data, doc.content_type, tenant.tenant_id
        )
        if not blocks:
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.FAILED, error="vision: no content"
            )
            LAYOUT_PROCESSED.labels(tenant=tenant.tenant_id, status="empty").inc()
            return
        # 清理旧索引内容（文本层降级结果或重试残留）
        await milvus_store.delete_by_doc(tenant, doc_id)
        await opensearch_store.delete_by_doc(tenant, doc_id)
        await doc_repo.delete_chunks_for_doc(session, tenant, doc_id)
        await _index_blocks(session, doc, tenant, blocks)
        LAYOUT_PROCESSED.labels(tenant=tenant.tenant_id, status="indexed").inc()
        log.info("layout.done doc_id=%s blocks=%s", doc_id, len(blocks))
    except Exception as e:  # noqa: BLE001
        LAYOUT_PROCESSED.labels(tenant=tenant.tenant_id, status="failed").inc()
        log.error("layout.failed doc_id=%s err=%s\n%s", doc_id, e, traceback.format_exc())
        try:
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.FAILED, error=f"vision: {type(e).__name__}: {e}"
            )
        except Exception:  # noqa: BLE001
            pass


async def process_layout_pending(session: AsyncSession, limit: int = 100) -> int:
    """扫描 status=layout_pending 的文档做视觉处理（Kafka 不可用时的轮询兜底）。"""
    from sqlalchemy import select
    from app.db.models import Document

    ids = (
        await session.execute(
            select(Document.id)
            .where(Document.status == DocumentStatus.LAYOUT_PENDING.value)
            .order_by(Document.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    for doc_id in ids:
        await process_layout(session, int(doc_id))
    return len(ids)
