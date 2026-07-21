"""解析中间表示：文档块（携带区域级溯源 page_no + bbox）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Block:
    """解析产出的最小单元：文本 + 页码 + 归一化 bbox。"""

    text: str
    page_no: Optional[int] = None
    bbox: Optional[List[float]] = None  # 归一化 [x0, y0, x1, y1]，0~1
    kind: str = "text"  # text | title | table | code | image_caption
    extra: dict = field(default_factory=dict)


@dataclass
class ParsedDoc:
    title: str
    blocks: List[Block]
    meta: dict = field(default_factory=dict)
    needs_vision: bool = False  # 是否应触发版面检测（扫描件/复杂排版）
