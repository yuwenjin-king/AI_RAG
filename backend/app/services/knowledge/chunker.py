"""分块策略（设计书 §4.2.3）。

首版实现：结构感知（按解析 block 聚合，大块再做固定长度 + 重叠切分）。
其它策略（语义/父子/版面区域）接口已预留：chunk_document 按 block 天然携带 bbox，
属"版面区域分块"的轻量实现；父子分块通过 parent_chunk_id 字段支持（首版不启用回溯）。
"""
from __future__ import annotations

from typing import List, Optional

from app.services.knowledge.block import ParsedDoc


def fixed_length(text: str, size: int = 800, overlap: int = 120) -> List[str]:
    """固定长度 + 重叠（通用兜底）。"""
    if not text:
        return []
    size = max(1, size)
    step = max(1, size - overlap)
    pieces: List[str] = []
    i = 0
    while i < len(text):
        pieces.append(text[i : i + size])
        if i + size >= len(text):
            break
        i += step
    return pieces


def chunk_document(
    parsed: ParsedDoc, *, max_size: int = 800, overlap: int = 120
) -> List[dict]:
    """产出 chunk dict 列表（含 page_no / bbox / ordinal）。"""
    chunks: List[dict] = []
    ordinal = 0

    if not parsed.blocks:
        return chunks

    for blk in parsed.blocks:
        text = (blk.text or "").strip()
        if not text:
            continue
        if len(text) <= max_size:
            pieces = [text]
        else:
            pieces = fixed_length(text, size=max_size, overlap=overlap)
        for j, piece in enumerate(pieces):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                {
                    "content": piece,
                    "page_no": blk.page_no,
                    "bbox": blk.bbox,
                    "ordinal": ordinal,
                    "extra": {
                        "kind": blk.kind,
                        "split_index": j,
                        "bbox_list": [blk.bbox] if blk.bbox else [],
                    },
                }
            )
            ordinal += 1
    return chunks
