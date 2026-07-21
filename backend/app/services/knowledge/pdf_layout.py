"""PDF 解析：分级策略（设计书 §4.2.2）。

（1）原生文本型 + 规整排版：直接读文本层 + 文本块坐标 bbox（覆盖大部分场景，零视觉成本）
（2）复杂排版 / 扫描件：触发版面检测（YOLO hook）——首版返回 needs_vision=True，由调用方决定是否走 OCR/版面
"""
from __future__ import annotations

from typing import List, Optional

from app.core.logging import get_logger
from app.services.knowledge.block import Block

log = get_logger(__name__)

# 启发式阈值（可配置）
_MIN_TEXT_RATIO = 0.02  # 文本层字符 / 页面面积比低于此 → 疑似扫描件


def _norm_bbox(rect, page_rect) -> Optional[List[float]]:
    """把 PDF 像素坐标归一化为 0~1（兼容不同渲染分辨率）。"""
    try:
        x0, y0, x1, y1 = rect
        w = page_rect.width
        h = page_rect.height
        if w <= 0 or h <= 0:
            return None
        return [
            max(0.0, min(1.0, x0 / w)),
            max(0.0, min(1.0, y0 / h)),
            max(0.0, min(1.0, x1 / w)),
            max(0.0, min(1.0, y1 / h)),
        ]
    except Exception:  # noqa: BLE001
        return None


def extract_blocks(data: bytes) -> tuple[List[Block], bool]:
    """返回 (blocks, needs_vision)。"""
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # noqa: BLE001
        log.warning("pdf.pymupdf.unavailable err=%s", e)
        return [], True  # 无解析器 → 标记需要视觉兜底

    blocks: List[Block] = []
    needs_vision = False
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        log.warning("pdf.open.failed err=%s", e)
        return [], True

    try:
        total_chars = 0
        total_area = 1
        for page_no, page in enumerate(doc, start=1):
            rect = page.rect
            total_area += rect.width * rect.height
            page_blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,no,type)
            page_chars = 0
            for b in page_blocks:
                x0, y0, x1, y1, text, _no, btype = b
                text = (text or "").strip()
                if btype != 0 or not text:  # 0=文本, 1=图片
                    continue
                page_chars += len(text)
                total_chars += len(text)
                bbox = _norm_bbox((x0, y0, x1, y1), rect)
                blocks.append(Block(text=text, page_no=page_no, bbox=bbox))
            # 启发式：本页几乎无文本层 → 疑似扫描件
            if page_chars == 0 and any(t == 1 for t in (pb[6] for pb in page_blocks)):
                needs_vision = True
        # 整体文本层覆盖率过低 → 触发视觉兜底
        if total_area > 0 and total_chars / (total_area / 1000) < _MIN_TEXT_RATIO:
            needs_vision = True
    finally:
        doc.close()

    log.info("pdf.extracted blocks=%s needs_vision=%s", len(blocks), needs_vision)
    return blocks, needs_vision


def detect_layout(data: bytes) -> Optional[List[Block]]:
    """版面检测入口（设计书 §4.2.2）。路由到配置的检测器：pymupdf 基线 / YOLO 视觉。

    首版 pymupdf 基线对原生文本 PDF 有效（改善多栏顺序）；YOLO 需模型+（建议）GPU，
    由 `settings.pdf_layout_detector=yolo` + `yolo_model_path` 启用。不可用时返回 None。
    """
    from app.services.knowledge.layout_detector import get_detector

    det = get_detector(settings.pdf_layout_detector, yolo_model_path=settings.yolo_model_path)
    if det is None:
        return None
    return det.detect(data)
