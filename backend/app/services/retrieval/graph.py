"""图召回（设计书 §4.4 GraphRAG 第三路）：查询实体 → 邻居 chunk。

作为 vector + keyword 之外的第三路召回，结果并入 RRF 融合。
"""
from __future__ import annotations

from typing import List, Optional

from app.core.config import settings
from app.core.metrics import GRAPH_RECALL
from app.core.tenant import TenantContext
from app.governance.authz import PermissionFilter
from app.infra import graph_store
from app.services.knowledge import graph as graph_mod


async def graph_recall(
    tenant: TenantContext, query: str, topk: int, *,
    permission: Optional[PermissionFilter] = None,
) -> tuple[List[dict], List[str]]:
    if not settings.graph_enabled or not graph_store.is_available():
        return [], []
    store = graph_store.get_store()
    if store is None:
        return [], ["graph.unavailable"]

    ents, _rels = await graph_mod.extract(query)
    if not ents:
        return [], []
    neighbors = store.query_neighbors(tenant.tenant_id, ents, topk)

    out: List[dict] = []
    for n in neighbors:
        doc_id = n.get("doc_id")
        if permission is not None and not permission.allows_doc(doc_id):
            continue
        out.append({
            "chunk_id": n["chunk_id"], "doc_id": doc_id,
            "score": float(n.get("score", 0.0)), "source": "graph",
        })
    GRAPH_RECALL.labels(result="hit" if out else "empty").inc()
    return out, []
