"""关键词召回（设计书 §4.4.2）：OpenSearch BM25，不可用时本地 BM25 兜底。"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.governance.authz import PermissionFilter
from app.infra import opensearch_store

log = get_logger(__name__)


async def keyword_recall(
    session: AsyncSession, tenant: TenantContext, query: str, topk: int, *,
    knowledge_base_id: Optional[int] = None, permission: Optional[PermissionFilter] = None,
) -> tuple[List[dict], List[str]]:
    degraded: List[str] = []
    if opensearch_store.is_available():
        hits = await opensearch_store.search_bm25(
            tenant, query, topk,
            knowledge_base_id=knowledge_base_id, permission=permission,
        )
        if hits:
            return hits, degraded
        # OpenSearch 在线但无命中 → 仍可尝试本地兜底（小语料更稳）
        degraded.append("keyword.empty_fallback")
    else:
        degraded.append("keyword.unavailable")
    local = await _local_bm25(
        session, tenant, query, topk,
        knowledge_base_id=knowledge_base_id, permission=permission,
    )
    return local, degraded


def _apply_permission(
    rows: list, permission: Optional[PermissionFilter]
) -> list:
    """对本地 BM25 候选做权限过滤（defense-in-depth；OpenSearch 路在服务端前置过滤）。"""
    if permission is None:
        return rows
    return [r for r in rows if _allowed(r.document_id, permission)]


def _allowed(doc_id: int, permission: PermissionFilter) -> bool:
    return permission.allows_doc(doc_id)


async def _local_bm25(
    session: AsyncSession, tenant: TenantContext, query: str, topk: int, *,
    knowledge_base_id: Optional[int], permission: Optional[PermissionFilter] = None,
) -> List[dict]:
    """基于 PG chunk 的本地 BM25（开发/兜底；语料大时用 OpenSearch）。

    权限前置过滤：按 permission.doc_ids / knowledge_base_ids / denied_doc_ids 收窄候选。
    """
    from app.services.retrieval.bm25_local import BM25

    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.content, Chunk.page_no, Chunk.bbox)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.tenant_id == tenant.tenant_id)
    )
    if knowledge_base_id is not None:
        stmt = stmt.where(Document.knowledge_base_id == knowledge_base_id)
    if permission:
        if permission.knowledge_base_ids is not None:
            stmt = stmt.where(Document.knowledge_base_id.in_(permission.knowledge_base_ids))
        if permission.doc_ids is not None:
            stmt = stmt.where(Chunk.document_id.in_(permission.doc_ids))
        if permission.denied_doc_ids is not None:
            stmt = stmt.where(Chunk.document_id.notin_(permission.denied_doc_ids))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    corpus = [r.content.split() for r in rows]
    bm25 = BM25(corpus)
    scores = bm25.get_scores(query.split())
    idx = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)[:topk]
    out: List[dict] = []
    for i in idx:
        if scores[i] <= 0:
            continue
        r = rows[i]
        out.append(
            {
                "chunk_id": r.id,
                "doc_id": r.document_id,
                "score": float(scores[i]),
                "content": r.content,
                "title": "",
                "page_no": r.page_no,
                "bbox": r.bbox,
                "source": "bm25_local",
            }
        )
    return out
