"""离线评估 runner（设计书 §9 / plan_four §2）：批量检索 → 算指标 → 聚合报告。

检索层（默认）：Recall@K / MRR / NDCG / 引用准确率 / bbox 溯源准确率。
生成层（可选，传入 generate 回调）：faithfulness（答案被上下文支撑比例）+ answer_overlap（答案-金标）。
generate 签名：async (query, context_str, chunks) -> answer_str。离线测试可注入 mock；
真实环境经 CLI --with-generation 注入 LLM（plan_four §3）。
"""
from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.eval import metrics as M
from app.repositories import eval as eval_repo
from app.repositories import governance as gov_repo
from app.schemas.chat import RetrievedChunk
from app.services.retrieval import orchestrator

log = get_logger(__name__)

GenerateFn = Callable[[str, str, List[RetrievedChunk]], Awaitable[str]]


async def run_eval(
    session: AsyncSession, tenant: TenantContext, scene_id: str, *,
    top_k: Optional[int] = None,
    generate: Optional[GenerateFn] = None,
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

        chunks = res.chunks if res else []
        # 文档级排名：同一文档的多个 chunk 去重（仅保留首次出现顺序），保证
        # recall@k / mrr / ndcg 在文档粒度一致，且 ndcg ∈ [0,1]。否则 DCG 把每个
        # 重复相关 chunk 都按位置计入、IDCG 却按去重后的相关文档数归一化 → nDCG 可 >1。
        seen: set = set()
        ranked_doc_ids: list = []
        for c in chunks:
            did = c.doc_id
            if did is not None and did not in seen:
                seen.add(did)
                ranked_doc_ids.append(did)
        row = {
            "case_id": case.id,
            "query": case.query,
            "n_retrieved": len(chunks),
            "recall@k": M.recall_at_k(ranked_doc_ids, case.expected_doc_ids or [], k),
            "mrr": M.mrr(ranked_doc_ids, case.expected_doc_ids or []),
            "ndcg": M.ndcg(ranked_doc_ids, case.expected_doc_ids or [], k),
            "citation_accuracy": M.citation_accuracy(ranked_doc_ids, case.expected_doc_ids or []),
        }
        if case.expected_bbox:
            pred_bbox = None
            for c in chunks:
                if c.doc_id in set(case.expected_doc_ids or []) and c.bbox:
                    pred_bbox = c.bbox
                    break
            row["bbox_accuracy"] = M.bbox_accuracy(pred_bbox, case.expected_bbox)
        if generate is not None:
            ctx_chunks = chunks
            context = "\n".join((c.content or "") for c in ctx_chunks)
            try:
                answer = await generate(case.query, context, ctx_chunks)
            except Exception as e:  # noqa: BLE001
                log.warning("eval.generate.failed case_id=%s err=%s", case.id, e)
                answer = ""
            row["answer"] = answer
            row["faithfulness"] = M.faithfulness(answer, [c.content for c in ctx_chunks])
            if case.expected_answer:
                row["answer_overlap"] = M.token_overlap(answer, case.expected_answer)
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
