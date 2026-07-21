"""引用标注（设计书 §4.5 后处理）：把检索 chunk 转成区域级引用。"""
from __future__ import annotations

from typing import List

from app.schemas.chat import Citation, RetrievedChunk


def build_citations(chunks: List[RetrievedChunk], max_n: int = 8) -> List[Citation]:
    out: List[Citation] = []
    for c in chunks[:max_n]:
        out.append(
            Citation(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                title=c.title,
                page_no=c.page_no,
                bbox=c.bbox,
                snippet=c.content[:200],
            )
        )
    return out
