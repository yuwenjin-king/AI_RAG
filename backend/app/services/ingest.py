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
from app.core.tenant import TenantContext
from app.db.models import DocumentStatus
from app.infra import object_storage, opensearch_store, milvus_store
from app.repositories import document as doc_repo
from app.services.ingestion import parser
from app.services.knowledge import chunker
from app.services.knowledge.embedding import get_provider

log = get_logger(__name__)


async def process_document(session: AsyncSession, doc_id: int) -> None:
    """处理单个文档的全链路（在传入 session 内执行；由调用方提交）。"""
    # 先取出文档（不带租户校验，因为 worker 跨租户）
    from sqlalchemy import select
    from app.db.models import Document

    doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        log.warning("ingest.doc_not_found doc_id=%s", doc_id)
        return

    tenant = TenantContext(tenant_id=doc.tenant_id)
    try:
        # 1) 读取原文
        await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.PARSING)
        data = object_storage.get_object_bytes(doc.object_key)

        # 2) 解析
        parsed = parser.parse(data, doc.content_type, doc.title)
        doc.title = parsed.title or doc.title

        # 3) 分块
        await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.CHUNKING)
        chunks = chunker.chunk_document(parsed)
        if not chunks:
            await doc_repo.set_status(
                session, tenant, doc_id, DocumentStatus.FAILED, error="no extractable text"
            )
            return

        # 4) embedding
        await doc_repo.set_status(session, tenant, doc_id, DocumentStatus.EMBEDDING)
        vectors = await get_provider().embed([c["content"] for c in chunks])
        if len(vectors) != len(chunks):
            # 对齐（极端情况下向量数不足）
            vectors = (vectors + [vectors[-1]] * len(chunks))[: len(chunks)]

        # 5) 写 PG chunks
        chunk_dicts: List[dict] = []
        for c, vec in zip(chunks, vectors):
            chunk_dicts.append(
                {
                    "tenant_id": tenant.tenant_id,
                    "document_id": doc_id,
                    "ordinal": c["ordinal"],
                    "content": c["content"],
                    "page_no": c.get("page_no"),
                    "bbox": c.get("bbox"),
                    "extra": c.get("extra", {}),
                    "vector_id": None,  # 占位，写完回填
                }
            )
        chunk_objs = await doc_repo.add_chunks(session, chunk_dicts)

        # 6) 双写向量库 + 倒排（vector_id = str(chunk.id)）
        milvus_records = []
        for idx, obj in enumerate(chunk_objs):
            milvus_records.append(
                {
                    "vector_id": str(obj.id),
                    "embedding": vectors[idx],
                    "tenant_id": tenant.tenant_id,
                    "doc_id": doc_id,
                    "chunk_id": obj.id,
                    "kb_id": doc.knowledge_base_id or 0,
                    "content": (obj.content or "")[:8192],
                }
            )
            obj.vector_id = str(obj.id)
        await session.flush()

        upserted = await milvus_store.upsert(tenant, milvus_records)

        os_docs = [
            {
                "chunk_id": obj.id,
                "doc_id": doc_id,
                "tenant_id": tenant.tenant_id,
                "knowledge_base_id": doc.knowledge_base_id or 0,
                "title": doc.title,
                "content": obj.content,
                "page_no": obj.page_no,
                "bbox": obj.bbox,
                "tags": [],
            }
            for obj in chunk_objs
        ]
        indexed = await opensearch_store.index_chunks(tenant, os_docs)

        meta_patch = {
            "pages": len({c.get("page_no") for c in chunks if c.get("page_no") is not None}) or None,
            "chunks": len(chunk_objs),
            "milvus_upserted": upserted,
            "opensearch_indexed": indexed,
        }
        await doc_repo.set_status(
            session, tenant, doc_id, DocumentStatus.INDEXED,
            embedding_status="done", meta_patch=meta_patch,
        )
        log.info(
            "ingest.done doc_id=%s tenant=%s chunks=%s milvus=%s os=%s",
            doc_id, tenant.tenant_id, len(chunk_objs), upserted, indexed,
        )
    except Exception as e:  # noqa: BLE001
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
