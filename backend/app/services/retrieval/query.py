"""查询理解（设计书 §4.4.1）：改写 / 扩展 / 路由。

- 改写：结合多轮历史做指代消解/省略补全（轻量 LLM，结果缓存）
- 扩展：生成语义不同的子查询，多路召回后统一 RRF
- 路由：判断应走哪些知识库 / 是否结构化查询
无 LLM key 或关闭开关时，均透传原 query（零降级风险）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.infra import redis_store

log = get_logger(__name__)

_REWRITE_SYS = (
    "你是查询改写助手。根据对话历史，把用户最新问题改写为可独立检索的完整查询"
    "（指代消解、省略补全）。只输出改写后的查询，不要解释、不要引号。"
    "若无历史或无需改写，原样输出。"
)
_EXPAND_SYS = (
    "你是查询扩展助手。为给定查询生成最多 2 条语义不同的扩展子查询"
    "（同义改写/相关角度），用于提升检索召回。每行一条，不要编号不要解释。"
)
_MAX_EXPANSIONS = 2


@dataclass
class QueryPlan:
    rewritten: str
    expansions: List[str]          # 改写后查询 + 扩展子查询
    knowledge_base_ids: Optional[List[int]] = None
    use_structured: bool = False


def _hash(query: str, history: Optional[List[dict]]) -> str:
    h = hashlib.sha256()
    h.update((query or "").encode())
    for m in history or []:
        h.update((str(m.get("role", "")) + ":" + str(m.get("content", ""))).encode())
    return h.hexdigest()[:16]


async def rewrite(query: str, history: Optional[List[dict]] = None) -> str:
    query = (query or "").strip()
    if not settings.llm_api_key or not settings.query_rewrite_enabled or not history:
        return query
    key = f"rewrite:{_hash(query, history)}"
    cached = await redis_store.cache_get(key)
    if cached:
        return cached
    try:
        from app.services.generation.llm_gateway import get_llm

        hist = "\n".join(f"{m.get('role')}: {m.get('content', '')}" for m in history[-6:])
        out = (await get_llm().complete([
            {"role": "system", "content": _REWRITE_SYS},
            {"role": "user", "content": f"对话历史:\n{hist}\n\n最新问题: {query}"},
        ])).strip().strip('"').strip()
        if out:
            await redis_store.cache_set(key, out, ttl=settings.query_rewrite_cache_ttl)
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("query.rewrite.failed transparent err=%s", e)
    return query


async def expand(query: str) -> List[str]:
    base = [(query or "").strip()]
    if not settings.llm_api_key or not settings.query_expansion_enabled:
        return base
    try:
        from app.services.generation.llm_gateway import get_llm

        out = await get_llm().complete([
            {"role": "system", "content": _EXPAND_SYS},
            {"role": "user", "content": query},
        ])
        seen: set[str] = {base[0]}
        exp: List[str] = []
        for line in out.splitlines():
            line = line.strip().lstrip("0123456789.-) ").strip().strip('"').strip()
            if line and line not in seen:
                seen.add(line)
                exp.append(line)
            if len(exp) >= _MAX_EXPANSIONS:
                break
        return base + exp
    except Exception as e:  # noqa: BLE001
        log.warning("query.expand.failed transparent err=%s", e)
        return base


async def plan(
    query: str,
    *,
    history: Optional[List[dict]] = None,
    knowledge_base_id: Optional[int] = None,
    scene=None,
) -> QueryPlan:
    rw = await rewrite(query, history)
    expansions = await expand(rw)
    return QueryPlan(
        rewritten=rw,
        expansions=expansions,
        knowledge_base_ids=[knowledge_base_id] if knowledge_base_id else None,
        use_structured=False,
    )
