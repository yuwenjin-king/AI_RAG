"""向量召回（设计书 §4.4.2）。"""
from __future__ import annotations

from typing import List, Optional

from app.core.tenant import TenantContext
from app.governance.authz import PermissionFilter
from app.infra import milvus_store
from app.services.knowledge.embedding import HashedBagEmbedding, embed_texts, get_provider


async def embed_query(query: str) -> tuple[List[float], bool]:
    """返回 (向量, is_mock)。走 embedding 缓存。"""
    provider = get_provider()
    vecs = await embed_texts([query])
    return vecs[0], isinstance(provider, HashedBagEmbedding)


async def vector_recall(
    tenant: TenantContext, query_vec: List[float], topk: int, *,
    knowledge_base_id: Optional[int] = None, permission: Optional[PermissionFilter] = None,
) -> tuple[List[dict], List[str]]:
    """返回 (hits, degraded_flags)。向量服务不可用 → 空 + degraded 标记。

    权限前置过滤：把 permission.doc_ids / knowledge_base_ids 作为 Milvus 标量过滤注入。
    """
    if not milvus_store.is_available():
        return [], ["vector.unavailable"]
    kb_ids = list(permission.knowledge_base_ids) if permission and permission.knowledge_base_ids else None
    doc_ids = list(permission.doc_ids) if permission and permission.doc_ids else None
    hits = await milvus_store.search(
        tenant, query_vec, topk,
        knowledge_base_id=knowledge_base_id, kb_ids=kb_ids, doc_ids=doc_ids,
    )
    if permission and permission.denied_doc_ids:
        hits = [h for h in hits if h.get("doc_id") not in permission.denied_doc_ids]
    return hits, []
