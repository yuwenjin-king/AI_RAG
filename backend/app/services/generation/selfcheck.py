"""答案自检（faithfulness，plan_three §2）。

生成后校验答案是否被检索证据支撑（不捏造、不矛盾）。
- 有 LLM key：LLM judge 输出 JSON {pass, score, reason}
- 无 key：启发式（非空 + 非降级 + 答案 token 在证据中的覆盖率）——离线可测
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.chat import RetrievedChunk
from app.services.retrieval.agentic import parse_json_loose

log = get_logger(__name__)


@dataclass
class SelfCheckResult:
    passed: bool
    score: float  # 0..1
    reason: str = ""


_SYS = (
    "你是答案事实一致性校验助手。判断【答案】是否被【证据】支撑（不捏造、不与证据矛盾）。"
    "严格只输出 JSON：{\"pass\": true/false, \"score\": 0..1, \"reason\": \"简短说明\"}。"
)

_FAILURE_MARKERS = ("生成失败", "未检索到相关", "降级 mock", "请检查 LLM")


def _heuristic(answer: str, chunks: List[RetrievedChunk]) -> SelfCheckResult:
    a = (answer or "").strip()
    if not a:
        return SelfCheckResult(False, 0.0, "empty answer")
    failure = any(m in a for m in _FAILURE_MARKERS)
    if not chunks:
        # 无证据可供校验：不判定为失败，给中性分
        return SelfCheckResult(passed=not failure, score=0.5 if not failure else 0.2, reason="no evidence")
    evidence = " ".join(c.content for c in chunks)
    toks = [t for t in re.split(r"[\s，。、；：！？]+", a) if len(t) > 1][:60]
    if not toks:
        return SelfCheckResult(not failure, 0.5 if not failure else 0.2, "no tokens")
    hit = sum(1 for t in toks if t in evidence)
    cov = hit / len(toks)
    passed = (not failure) and cov >= 0.3
    score = round(0.5 * (0.0 if failure else 1.0) + 0.5 * cov, 3)
    return SelfCheckResult(passed, score, f"heuristic coverage={cov:.2f}")


async def _llm_check(answer: str, chunks: List[RetrievedChunk]) -> SelfCheckResult:
    from app.services.generation.llm_gateway import get_llm

    evidence = "\n".join(f"[{i}] {c.content[:200]}" for i, c in enumerate(chunks[:6], 1))
    out = await get_llm().complete([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"证据：\n{evidence or '（无）'}\n\n答案：{answer}"},
    ])
    data = parse_json_loose(out) or {}
    passed = bool(data.get("pass", False))
    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return SelfCheckResult(passed, max(0.0, min(1.0, score)), str(data.get("reason", "")))


async def check_faithfulness(answer: str, chunks: List[RetrievedChunk]) -> SelfCheckResult:
    """有 LLM key→LLM judge；否则启发式。LLM 失败回退启发式。"""
    if not settings.llm_api_key:
        return _heuristic(answer, chunks)
    try:
        return await _llm_check(answer, chunks)
    except Exception as e:  # noqa: BLE001
        log.warning("selfcheck.llm_failed fallback_heuristic err=%s", e)
        return _heuristic(answer, chunks)
