"""OCR hook（设计书 §4.2.2，扫描件/区域级识别）。

首版为 NoOp，扫描件无文本时调用方记录降级。接入 PaddleOCR 时实现 OCREngine.recognize。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.services.knowledge.block import Block


class OCREngine(ABC):
    @abstractmethod
    def recognize(self, page_image_bytes: bytes, page_no: int) -> List[Block]:
        ...


class NoOpOCR(OCREngine):
    """占位：不产生任何文本。"""

    def recognize(self, page_image_bytes: bytes, page_no: int) -> List[Block]:  # noqa: D401
        return []


_engine: Optional[OCREngine] = None


def get_engine() -> OCREngine:
    global _engine
    if _engine is None:
        _engine = NoOpOCR()
    return _engine
