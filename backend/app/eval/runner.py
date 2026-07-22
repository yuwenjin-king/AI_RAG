"""离线评估 runner（设计书 §9）：批量检索 → 算指标 → 聚合报告。

仅跑检索层指标（Recall@K / MRR / NDCG / 引用准确率 / bbox 溯源准确率），确定可回归。
生成层忠实度（faithfulness，需 LLM judge）作为后续扩展。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.eval import metrics as M
from app.repositories import eval as eval_repo
from app.repositories import governance as gov_repo
from app.services.retrieval import orchestrator

log = get_logger(__name__)


async def run_eval(
    session: AsyncSession, tenant: TenantContext, scene_id: str, *,
    top_k: Optional[int] = None,
) -> dict:
    cases = await eval_repo.list_cases(session, tenant, scene_id)
    if not cases:
        return {"scene_id": scene_id, "tenant": tenant.tenant_id, "n_cases": 0,
                "note": "no eval cases for this scene"}

    scene = await gov_repo.get_scene(session, tenant, scene_id)
    kb_id = (scene.knowledge_base_ids or [None])[0] if scene and scene.knowledge_base_ids else None
    k = top_k or settings.retrieval_final_topk

    per_case: List[dict] = []
    for case in cases:
        try:
            res = await orchestrator.retrieve(
                session, tenant, case.query,
                knowledge_base_id=kb_id, top_k=k, scene=scene, permission=None,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("eval.case.failed case_id=%s err=%s", case.id, e)
            res = None

        retrieved_doc_ids = [c.doc_id for c in (res.chunks if res else [])]
        row = {
            "case_id": case.id,
            "query": case.query,
            "recall@k": M.recall_at_k(retrieved_doc_ids, case.expected_doc_ids or [], k),
            "mrr": M.mrr(retrieved_doc_ids, case.expected_doc_ids or []),
            "ndcg": M.ndcg(retrieved_doc_ids, case.expected_doc_ids or [], k),
            "citation_accuracy": M.citation_accuracy(retrieved_doc_ids, case.expected_doc_ids or []),
        }
        if case.expected_bbox:
            pred_bbox = None
            for c in (res.chunks if res else []):
                if c.doc_id in set(case.expected_doc_ids or []) and c.bbox:
                    pred_bbox = c.bbox
                    break
            row["bbox_accuracy"] = M.bbox_accuracy(pred_bbox, case.expected_bbox)
        per_case.append(row)

    keys = sorted({k for c in per_case for k in c if k not in ("case_id", "query")})
    agg = M.aggregate(per_case, keys)
    return {
        "scene_id": scene_id,
        "tenant": tenant.tenant_id,
        "top_k": k,
        **agg,
        "cases": per_case,
    }
