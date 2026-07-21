"""关键词召回（设计书 §4.4.2）：OpenSearch BM25，不可用时本地 BM25 兜底。"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.infra import opensearch_store

log = get_logger(__name__)


async def keyword_recall(
    session: AsyncSession, tenant: TenantContext, query: str, topk: int, *,
    knowledge_base_id: Optional[int] = None,
) -> tuple[List[dict], List[str]]:
    degraded: List[str] = []
    if opensearch_store.is_available():
        hits = await opensearch_store.search_bm25(
            tenant, query, topk, knowledge_base_id=knowledge_base_id
        )
        if hits:
            return hits, degraded
        # OpenSearch 在线但无命中 → 仍可尝试本地兜底（小语料更稳）
        degraded.append("keyword.empty_fallback")
    else:
        degraded.append("keyword.unavailable")
    local = await _local_bm25(session, tenant, query, topk, knowledge_base_id=knowledge_base_id)
    return local, degraded


async def _local_bm25(
    session: AsyncSession, tenant: TenantContext, query: str, topk: int, *,
    knowledge_base_id: Optional[int],
) -> List[dict]:
    """基于 PG 全量 chunk 的本地 BM25（开发/兜底用；语料大时应使用 OpenSearch）。"""
    from app.services.retrieval.bm25_local import BM25

    stmt = select(Chunk.id, Chunk.document_id, Chunk.content, Chunk.page_no, Chunk.bbox).where(
        Chunk.tenant_id == tenant.tenant_id
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    corpus = [r.content.split() for r in rows]
    bm25 = BM25(corpus)
    q_tokens = query.split()
    scores = bm25.get_scores(q_tokens)
    idx = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)[:topk]
    # 仅返回有得分项
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
