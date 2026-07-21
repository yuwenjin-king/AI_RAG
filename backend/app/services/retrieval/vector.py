"""向量召回（设计书 §4.4.2）。"""
from __future__ import annotations

from typing import List, Optional

from app.core.tenant import TenantContext
from app.infra import milvus_store
from app.services.knowledge.embedding import get_provider


async def embed_query(query: str) -> tuple[List[float], bool]:
    """返回 (向量, is_mock)。"""
    provider = get_provider()
    vecs = await provider.embed([query])
    from app.services.knowledge.embedding import HashedBagEmbedding

    return vecs[0], isinstance(provider, HashedBagEmbedding)


async def vector_recall(
    tenant: TenantContext, query_vec: List[float], topk: int, *,
    knowledge_base_id: Optional[int] = None,
) -> tuple[List[dict], List[str]]:
    """返回 (hits, degraded_flags)。向量服务不可用 → 空 + degraded 标记。"""
    if not milvus_store.is_available():
        return [], ["vector.unavailable"]
    hits = await milvus_store.search(
        tenant, query_vec, topk, knowledge_base_id=knowledge_base_id
    )
    return hits, []
