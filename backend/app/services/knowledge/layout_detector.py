"""版面检测（设计书 §4.2.2）。

分级可插拔：
- PymupdfDictDetector：基于 PDF 文本层的结构化抽取（块/行 + bbox），改善多栏阅读顺序，零额外依赖。
- DocLayoutYoloDetector：YOLO 类视觉版面检测（ultralytics），处理复杂排版/扫描件，需模型+（建议）GPU。
detect() 返回带 bbox 的 Block 列表；不可用/未配置时返回 None，调用方降级。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.core.logging import get_logger
from app.services.knowledge.block import Block
from app.services.knowledge.pdf_layout import _norm_bbox

log = get_logger(__name__)


class LayoutDetector(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self, data: bytes) -> Optional[List[Block]]:
        """返回带 page_no + 归一化 bbox 的 Block 列表；不适用/失败返回 None。"""
        ...


class PymupdfDictDetector(LayoutDetector):
    """用 PyMuPDF 的 dict 模式按"块-行"结构抽取，优于 flat blocks 的多栏乱序。

    对原生文本型 PDF（含复杂排版）有效；扫描件无文本层 → 返回 None（交给 OCR 路）。
    """

    name = "pymupdf_dict"

    def detect(self, data: bytes) -> Optional[List[Block]]:
        try:
            import fitz  # PyMuPDF
        except Exception as e:  # noqa: BLE001
            log.warning("layout.pymupdf.unavailable err=%s", e)
            return None
        blocks: List[Block] = []
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as e:  # noqa: BLE001
            log.warning("layout.pymupdf.open.failed err=%s", e)
            return None
        try:
            for page_no, page in enumerate(doc, start=1):
                rect = page.rect
                d = page.get_text("dict")
                for blk in d.get("blocks", []):
                    if blk.get("type") != 0:  # 0=文本
                        continue
                    lines_text = []
                    for line in blk.get("lines", []):
                        spans = [sp.get("text", "") for sp in line.get("spans", [])]
                        lines_text.append("".join(spans))
                    text = "\n".join(s for s in lines_text if s).strip()
                    if not text:
                        continue
                    bbox = _norm_bbox(blk.get("bbox", (0, 0, 0, 0)), rect)
                    blocks.append(Block(text=text, page_no=page_no, bbox=bbox))
            doc.close()
        except Exception as e:  # noqa: BLE001
            log.warning("layout.pymupdf.extract.failed err=%s", e)
            return None
        return blocks or None


class DocLayoutYoloDetector(LayoutDetector):
    """YOLO 视觉版面检测（ultralytics）。

    流程：PDF 页面→图片→模型推理→区域(bbox)+类别→按区域类型分流（正文/标题直取文本或 OCR，表格走专用识别）。
    需安装 ultralytics 并提供版面检测模型权重；未就绪时返回 None（降级）。
    """

    name = "doclayout_yolo"

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._model = None

    def _load(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.model_path)
        return self._model

    def detect(self, data: bytes) -> Optional[List[Block]]:
        try:
            import fitz  # 渲染页面用
            model = self._load()
        except Exception as e:  # noqa: BLE001
            log.warning("layout.yolo.unavailable err=%s", e)
            return None
        blocks: List[Block] = []
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            for page_no, page in enumerate(doc, start=1):
                rect = page.rect
                pix = page.get_pixmap(dpi=160)
                import cv2
                import numpy as np

                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR) if pix.n >= 4 else img
                results = model(img, verbose=False)
                scale_x = rect.width / pix.width
                scale_y = rect.height / pix.height
                for r in results:
                    for box in r.boxes:
                        x0, y0, x1, y1 = box.xyxy[0].tolist()
                        cls = int(box.cls[0])
                        label = model.names.get(cls, str(cls))
                        bbox = _norm_bbox(
                            (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y), rect
                        )
                        # 文本内容交给 OCR（区域级）或文本层；此处仅产出区域框
                        blocks.append(
                            Block(text="", page_no=page_no, bbox=bbox, kind=label, extra={"yolo_cls": cls})
                        )
            doc.close()
        except Exception as e:  # noqa: BLE001
            log.warning("layout.yolo.detect.failed err=%s", e)
            return None
        return blocks or None


def get_detector(name: str = "auto", *, yolo_model_path: str = "") -> Optional[LayoutDetector]:
    name = (name or "auto").lower()
    if name == "yolo" or name == "doclayout_yolo":
        if not yolo_model_path:
            log.warning("layout.yolo.no_model_path")
            return None
        return DocLayoutYoloDetector(yolo_model_path)
    # auto / pymupdf → 基线（无额外依赖，原生 PDF 优先）
    return PymupdfDictDetector()
