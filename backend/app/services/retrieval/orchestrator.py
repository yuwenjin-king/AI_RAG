"""检索编排（设计书 §4.4 四段流水线）。

查询理解 → 多路召回 → RRF 融合（+ 可选 rerank）→ 上下文构建（区域级溯源富化）。
"""
from __future__ import annotations

import asyncio
import time
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.metrics import DEGRADED, RECALL_CHUNKS, RETRIEVAL_LATENCY
from app.core.tenant import TenantContext
from app.repositories import document as doc_repo
from app.schemas.chat import RetrieveResponse, RetrievedChunk
from app.services.retrieval import fusion, keyword, query as query_mod, reranker, vector

Stage = List[str]  # degraded flags


def _observe(tenant_id: str, n_chunks: int, degraded: List[str], elapsed: float) -> None:
    RETRIEVAL_LATENCY.labels(tenant=tenant_id).observe(elapsed)
    RECALL_CHUNKS.observe(n_chunks)
    for k in set(degraded):
        DEGRADED.labels(kind=k).inc()


async def retrieve(
    session: AsyncSession, tenant: TenantContext, query: str, *,
    knowledge_base_id: Optional[int] = None, top_k: Optional[int] = None,
    scene=None,
) -> RetrieveResponse:
    start = time.perf_counter()
    topk = top_k or settings.retrieval_final_topk
    recall_k = max(settings.retrieval_vector_topk, settings.retrieval_keyword_topk)
    degraded: List[str] = []

    # 1) 查询理解
    plan = query_mod.plan(query, knowledge_base_id=knowledge_base_id, scene=scene)

    # 2) 向量化查询
    query_vec, is_mock = await vector.embed_query(plan.rewritten)
    if is_mock:
        degraded.append("embedding.mock")

    # 3) 多路召回（并行）
    vec_hits, v_deg = await vector.vector_recall(
        tenant, query_vec, recall_k, knowledge_base_id=knowledge_base_id
    )
    kw_hits, k_deg = await keyword.keyword_recall(
        session, tenant, plan.rewritten, recall_k, knowledge_base_id=knowledge_base_id
    )
    degraded.extend(v_deg)
    degraded.extend(k_deg)

    # 4) RRF 融合
    fused = fusion.rrf_fuse(vec_hits, kw_hits)
    if not fused:
        # 全部召回路失败/为空
        degraded = sorted(set(degraded))
        _observe(tenant.tenant_id, 0, degraded, time.perf_counter() - start)
        return RetrieveResponse(query=plan.rewritten, chunks=[], degraded=degraded)

    # 5) 精排（无配置时 NoOp，保持 RRF 顺序）
    ranked = await reranker.get_reranker().rerank(plan.rewritten, fused, topk)

    # 6) 上下文富化：补全 bbox/title/page_no（向量路缺失）
    chunk_ids = [c.get("chunk_id") for c in ranked if c.get("chunk_id") is not None]
    enrich = {e["chunk_id"]: e for e in await doc_repo.fetch_enriched(session, tenant, chunk_ids)}

    chunks: List[RetrievedChunk] = []
    for c in ranked:
        cid = c.get("chunk_id")
        e = enrich.get(cid, {})
        chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                doc_id=c.get("doc_id") or e.get("document_id"),
                title=e.get("title", c.get("title", "")),
                content=e.get("content", c.get("content", "")),
                page_no=e.get("page_no", c.get("page_no")),
                bbox=e.get("bbox", c.get("bbox")),
                score=float(c.get("score", c.get("rrf_score", 0.0))),
                source=c.get("source", "fused"),
            )
        )

    # 去重降级标记
    degraded = sorted(set(degraded))
    _observe(tenant.tenant_id, len(chunks), degraded, time.perf_counter() - start)
    # 向量不可用 → 仅 BM25（设计书 §7 降级）已隐含体现在 v_deg
    return RetrieveResponse(query=plan.rewritten, chunks=chunks, degraded=degraded)
