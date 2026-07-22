"""实体/关系抽取（设计书 §4.3 GraphRAG）。

- LLM 抽取（JSON：entities + relations），需 key；失败/无 key → 启发式兜底
- 启发式：英文大写词 + 中文 ≥2 字串（去停用词），确定可测
"""
from __future__ import annotations

import json
import re
from typing import List, Tuple

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "with", "this", "that", "it", "as", "by", "at", "from",
}
_WORD_RE = re.compile(r"[A-Z][A-Za-z0-9_\-]{1,}")
_CJK_RE = re.compile(r"[一-鿿]{2,}")

_LLM_SYS = (
    "你是实体关系抽取器。从文本抽取关键实体与关系，输出 JSON："
    '{"entities":["实体1",...],"relations":[["主体","关系","客体"],...]}。'
    "实体小写、精炼；只输出 JSON，不要解释。"
)


def _extract_heuristic(text: str) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    ents: set[str] = set()
    for m in _WORD_RE.findall(text or ""):
        w = m.lower()
        if w not in _STOP and len(w) >= 3:
            ents.add(w)
    for m in _CJK_RE.findall(text or ""):
        ents.add(m)
    return sorted(ents)[:12], []


async def _extract_llm(text: str) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    from app.services.generation.llm_gateway import get_llm

    raw = await get_llm().complete([
        {"role": "system", "content": _LLM_SYS},
        {"role": "user", "content": (text or "")[:2000]},
    ])
    data = json.loads(raw.strip().strip("`"))
    ents = [str(e).strip().lower() for e in data.get("entities", []) if str(e).strip()]
    rels: List[Tuple[str, str, str]] = []
    for r in data.get("relations", []):
        if isinstance(r, list) and len(r) >= 3:
            rels.append((str(r[0]).lower(), str(r[1]), str(r[2]).lower()))
    return ents[:20], rels


async def extract(text: str) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    """返回 (entities, relations)。按配置选择 LLM / 启发式；LLM 失败回退启发式。"""
    method = (settings.graph_extraction or "auto").lower()
    if method in ("auto", "llm") and settings.llm_api_key:
        try:
            ents, rels = await _extract_llm(text)
            if ents:
                return ents, rels
        except Exception as e:  # noqa: BLE001
            log.warning("graph.extract.llm_failed fallback=heuristic err=%s", e)
    return _extract_heuristic(text)
