"""Agentic RAG：检索充分性评估 + 迭代召回（plan_three §2）。

把单次 retrieve→generate 升级为 agent loop：
  recall → 评估(证据是否足以回答) → 不足则生成 followup 子查询 → 再召回 → 去重合并 → 再评估
- 有 LLM key：充分性/followup 由 LLM 一次调用产出 JSON {sufficient,score,followups}
- 无 key：启发式（chunk 数 + 查询词覆盖；followup 按连接符切分）——离线可测
迭代有上限（agentic_max_iterations），无新证据即收敛，防发散。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import AGENTIC_ITERATIONS, SUFFICIENCY_SCORE
from app.core.tenant import TenantContext
from app.core import tracing
from app.governance.authz import PermissionFilter
from app.schemas.chat import RetrievedChunk
from app.services.retrieval import orchestrator

log = get_logger(__name__)


@dataclass
class SufficiencyAssessment:
    sufficient: bool
    score: float  # 0..1
    followups: List[str] = field(default_factory=list)


@dataclass
class AgenticResult:
    chunks: List[RetrievedChunk]
    iterations: int
    sufficiency_score: float
    followups_used: List[str]
    degraded: List[str]


def parse_json_loose(text: str) -> Optional[dict]:
    """从 LLM 输出中宽松解析单个 JSON 对象（容忍 ```json``` 包裹/前后噪音）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ===== 启发式 =====
_STOP = set("的了吗呢吧啊我你他她它们是在有和与及或一个这个那些很也都要把被让".split())
_SPLIT_RE = re.compile(r"[、,，;；。？\?！!]|以及|还有|并且|而且| and | or ")


def _keywords(query: str) -> List[str]:
    toks = [t for t in re.split(r"[\s、,，。？\?！!；;：:]+", query) if t]
    return [t for t in toks if t not in _STOP and len(t) > 0]


def _coverage(query: str, chunks: List[RetrievedChunk]) -> float:
    kws = _keywords(query)
    if not kws:
        return 1.0 if chunks else 0.0
    text = " ".join(c.content for c in chunks)
    hit = sum(1 for k in kws if k in text)
    return hit / len(kws)


def _heuristic_followups(query: str) -> List[str]:
    parts = [p.strip() for p in _SPLIT_RE.split(query) if p and p.strip()]
    parts = [p for p in parts if p not in _STOP]
    seen = {query.strip()}
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:2]


def _heuristic_assess(query: str, chunks: List[RetrievedChunk]) -> SufficiencyAssessment:
    cov = _coverage(query, chunks)
    n = len(chunks)
    need = max(1, settings.agentic_sufficient_topk)
    sufficient = n >= need and cov >= 0.5
    score = round(0.5 * (min(n, need) / need) + 0.5 * cov, 3)
    followups: List[str] = []
    if not sufficient:
        followups = _heuristic_followups(query)
    return SufficiencyAssessment(sufficient=sufficient, score=max(0.0, min(1.0, score)), followups=followups)


# ===== LLM judge =====
_JUDGE_SYS = (
    "你是检索充分性评估助手。判断给定检索片段是否足以回答用户问题。"
    "严格只输出 JSON：{\"sufficient\": true/false, \"score\": 0..1, \"followups\": [\"子查询\", ...]}。"
    "score=证据充分程度；若 sufficient=false，followups 给出至多 2 条用于二次检索的补全子查询。"
    "不要输出 JSON 以外的任何文字。"
)


async def _llm_assess(query: str, chunks: List[RetrievedChunk]) -> SufficiencyAssessment:
    from app.services.generation.llm_gateway import get_llm

    snippets = "\n".join(f"[{i}] {c.content[:200]}" for i, c in enumerate(chunks[:6], 1))
    out = await get_llm().complete([
        {"role": "system", "content": _JUDGE_SYS},
        {"role": "user", "content": f"问题：{query}\n\n检索片段：\n{snippets or '（无）'}"},
    ])
    data = parse_json_loose(out) or {}
    sufficient = bool(data.get("sufficient", False))
    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    followups = [str(x).strip() for x in (data.get("followups") or []) if str(x).strip()][:2]
    return SufficiencyAssessment(sufficient=sufficient, score=max(0.0, min(1.0, score)), followups=followups)


async def assess_sufficiency(query: str, chunks: List[RetrievedChunk]) -> SufficiencyAssessment:
    """有 LLM key→LLM judge；否则启发式。LLM 失败回退启发式。"""
    if not settings.llm_api_key:
        return _heuristic_assess(query, chunks)
    try:
        return await _llm_assess(query, chunks)
    except Exception as e:  # noqa: BLE001
        log.warning("agentic.sufficiency.llm_failed fallback_heuristic err=%s", e)
        return _heuristic_assess(query, chunks)


# ===== 合并 =====
def _stable_key(c: RetrievedChunk):
    if c.chunk_id is not None:
        return ("id", c.chunk_id)
    return ("h", hash(c.content))


def merge_chunks(accum: List[RetrievedChunk], new: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """按 chunk_id 去重，保留得分更高者。"""
    by_key: dict = {}
    for c in list(accum) + list(new):
        k = _stable_key(c)
        prev = by_key.get(k)
        if prev is None or (c.score or 0.0) > (prev.score or 0.0):
            by_key[k] = c
    return list(by_key.values())


# ===== 迭代召回 =====
async def agentic_retrieve(
    session: AsyncSession, tenant: TenantContext, query: str, *,
    knowledge_base_id: Optional[int] = None, top_k: Optional[int] = None,
    scene=None, history: Optional[List[dict]] = None,
    permission: Optional[PermissionFilter] = None,
    max_iterations: Optional[int] = None,
) -> AgenticResult:
    max_iter = max(1, max_iterations if max_iterations is not None else settings.agentic_max_iterations)
    degraded: List[str] = []
    followups_used: List[str] = []

    first = await orchestrator.retrieve(
        session, tenant, query, knowledge_base_id=knowledge_base_id,
        top_k=top_k, scene=scene, history=history, permission=permission,
    )
    degraded.extend(first.degraded)
    merged = list(first.chunks)
    last_score = 0.0
    iterations = 1

    while iterations < max_iter:
        with tracing.span("agentic.assess", iteration=iterations):
            assessment = await assess_sufficiency(query, merged)
        last_score = assessment.score
        if assessment.sufficient or not assessment.followups:
            break
        progressed = False
        for sub in assessment.followups:
            if sub == query.strip() or sub in followups_used:
                continue
            followups_used.append(sub)
            r = await orchestrator.retrieve(
                session, tenant, sub, knowledge_base_id=knowledge_base_id,
                top_k=top_k, scene=scene, permission=permission,
            )
            degraded.extend(r.degraded)
            before = len(merged)
            merged = merge_chunks(merged, list(r.chunks))
            if len(merged) > before:
                progressed = True
        iterations += 1
        if not progressed:
            break  # 无新证据 → 收敛

    if last_score == 0.0:
        try:
            with tracing.span("agentic.assess", iteration=iterations, final=True):
                last_score = (await assess_sufficiency(query, merged)).score
        except Exception:  # noqa: BLE001
            last_score = 0.0

    # 按分数排序，截断（迭代可能带来更多有用上下文，故放宽到 final_topk 的 2 倍）
    final_k = top_k or settings.retrieval_final_topk
    cap = max(final_k, settings.retrieval_final_topk) * 2
    merged.sort(key=lambda c: c.score or 0.0, reverse=True)
    chunks = merged[:cap]

    AGENTIC_ITERATIONS.observe(iterations)
    SUFFICIENCY_SCORE.observe(last_score)
    degraded.append("agentic")
    return AgenticResult(
        chunks=chunks, iterations=iterations,
        sufficiency_score=last_score, followups_used=followups_used,
        degraded=sorted(set(degraded)),
    )
