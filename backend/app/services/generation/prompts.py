"""Prompt 模板中心（设计书 §4.5）。首版内置 RAG 问答模板，按场景可覆盖。"""
from __future__ import annotations

from typing import List, Optional

from app.schemas.chat import RetrievedChunk

DEFAULT_SYSTEM = (
    "你是一个严谨的企业知识问答助手。请仅根据下方【参考资料】回答用户问题。"
    "若资料不足以回答，请直接说明未检索到相关信息，不要编造。"
    "回答中引用资料时，用形如 [1]、[2] 的标注，对应参考资料的序号。"
)

DEFAULT_TEMPLATE = """【参考资料】
{context}

【用户问题】
{query}
"""


def render_context(chunks: List[RetrievedChunk]) -> str:
    if not chunks:
        return "（未检索到相关资料）"
    lines = []
    for i, c in enumerate(chunks, start=1):
        loc = f"（第{c.page_no}页）" if c.page_no else ""
        # Small-to-Big：用回溯到的父块上下文（context），引用仍精确到子块
        body = c.context or c.content
        lines.append(f"[{i}] 《{c.title}》{loc}\n{body}")
    return "\n\n".join(lines)


def build_messages(
    query: str, chunks: List[RetrievedChunk], *,
    history: Optional[List[dict]] = None, system: Optional[str] = None,
) -> List[dict]:
    msgs: List[dict] = [{"role": "system", "content": system or DEFAULT_SYSTEM}]
    for h in history or []:
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            msgs.append({"role": role, "content": h["content"]})
    user = DEFAULT_TEMPLATE.format(context=render_context(chunks), query=query)
    msgs.append({"role": "user", "content": user})
    return msgs
