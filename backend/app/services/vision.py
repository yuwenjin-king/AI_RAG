"""视觉解析编排（设计书 §4.2.2）：版面检测 + 区域级 OCR。

扫描件走 OCR（按页渲染→识别→带 bbox 文本块）；复杂原生走版面检测（pymupdf 基线 / YOLO）。
所有重型库（fitz/ultralytics/paddleocr/cv2）懒加载，缺失时优雅降级。
"""
from __future__ import annotations

from typing import List, Tuple

from app.core.logging import get_logger
from app.services.knowledge import ocr as ocr_mod, pdf_layout
from app.services.knowledge.block import Block

log = get_logger(__name__)


def _render_pages_png(data: bytes) -> List[Tuple[int, bytes]]:
    """PyMuPDF 按页渲染为 PNG 字节。"""
    import fitz  # PyMuPDF

    out: List[Tuple[int, bytes]] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page_no, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=200)
            out.append((page_no, pix.tobytes("png")))
    finally:
        doc.close()
    return out


def extract_with_vision(data: bytes, *, content_type: str = "", tenant_id: str = "") -> List[Block]:
    """对扫描件/复杂 PDF 做视觉解析，返回带 page_no + 归一化 bbox 的 Block。

    策略：OCR 引擎可用 → 逐页 OCR（扫描件取文本）；否则版面检测（原生复杂件取结构块）。
    """
    ocr = ocr_mod.get_engine()
    blocks: List[Block] = []
    if ocr.name != "none":
        try:
            pages = _render_pages_png(data)
            chars = 0
            for page_no, png in pages:
                page_blocks = ocr.recognize(png, page_no)
                blocks.extend(page_blocks)
                chars += sum(len(b.text) for b in page_blocks)
            if tenant_id:
                from app.core.metrics import OCR_CHARS

                OCR_CHARS.labels(tenant=tenant_id).inc(chars)
            if blocks:
                log.info("vision.ocr pages=%s chars=%s", len(pages), chars)
                return blocks
        except Exception as e:  # noqa: BLE001
            log.warning("vision.ocr.failed fallback_layout err=%s", e)

    det = pdf_layout.detect_layout(data)
    if det:
        log.info("vision.layout blocks=%s", len(det))
    return det or []
