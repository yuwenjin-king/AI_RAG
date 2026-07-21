"""OCR hook（设计书 §4.2.2，扫描件/区域级识别）。

- NoOpOCR：占位（默认），不产生文本
- PaddleOCREngine：区域级 OCR（paddleocr），需安装 + （建议）GPU
按 settings.ocr_engine 选择；不可用降级为 NoOp。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.knowledge.block import Block

log = get_logger(__name__)


class OCREngine(ABC):
    name: str = "base"

    @abstractmethod
    def recognize(self, page_image_bytes: bytes, page_no: int) -> List[Block]:
        ...


class NoOpOCR(OCREngine):
    name = "none"

    def recognize(self, page_image_bytes: bytes, page_no: int) -> List[Block]:  # noqa: D401
        return []


class PaddleOCREngine(OCREngine):
    """PaddleOCR 区域级识别：返回带归一化 bbox 的文本块。"""

    name = "paddle"

    def __init__(self, lang: str = "ch"):
        self.lang = lang
        self._ocr = None

    def _load(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
        return self._ocr

    def recognize(self, page_image_bytes: bytes, page_no: int) -> List[Block]:
        try:
            import cv2
            import numpy as np

            engine = self._load()
            img = cv2.imdecode(np.frombuffer(page_image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return []
            h, w = img.shape[:2]
            result = engine.ocr(img, cls=True)
            blocks: List[Block] = []
            for line in (result[0] if result and result[0] else []):
                box, info = line
                txt, _conf = info
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                if w > 0 and h > 0:
                    bbox = [
                        max(0.0, min(1.0, min(xs) / w)),
                        max(0.0, min(1.0, min(ys) / h)),
                        max(0.0, min(1.0, max(xs) / w)),
                        max(0.0, min(1.0, max(ys) / h)),
                    ]
                else:
                    bbox = None
                if txt and txt.strip():
                    blocks.append(Block(text=txt.strip(), page_no=page_no, bbox=bbox))
            return blocks
        except Exception as e:  # noqa: BLE001
            log.warning("ocr.paddle.failed err=%s", e)
            return []


_engine: Optional[OCREngine] = None


def get_engine() -> OCREngine:
    global _engine
    if _engine is not None:
        return _engine
    if (settings.ocr_engine or "none").lower() == "paddle":
        log.info("ocr.engine=paddle")
        _engine = PaddleOCREngine()
    else:
        _engine = NoOpOCR()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
