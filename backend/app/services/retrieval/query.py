"""查询理解（设计书 §4.4.1）：改写 / 扩展 / 路由。

首版为"透明"实现（透传原 query），接口已预留：
- 改写：接轻量 LLM 做指代消解（多轮历史 → 完整 query）
- 扩展：同义词 / 领域术语扩展为多个子查询
- 路由：判断应走哪些知识库 / 是否 Text2SQL
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class QueryPlan:
    rewritten: str
    expansions: List[str]          # 扩展子查询（首版仅含原 query）
    knowledge_base_ids: Optional[List[int]] = None
    use_structured: bool = False   # 是否需结构化查询（Text2SQL 等）


def rewrite(query: str, history: Optional[List[dict]] = None) -> str:
    """多轮改写（首版透传；接入 LLM 时替换）。"""
    return query.strip()


def expand(query: str) -> List[str]:
    """查询扩展（首版仅原 query）。"""
    return [query.strip()]


def plan(
    query: str,
    *,
    history: Optional[List[dict]] = None,
    knowledge_base_id: Optional[int] = None,
    scene=None,
) -> QueryPlan:
    rw = rewrite(query, history)
    return QueryPlan(
        rewritten=rw,
        expansions=expand(rw),
        knowledge_base_ids=[knowledge_base_id] if knowledge_base_id else None,
        use_structured=False,
    )
