"""版面检测 / OCR Worker（设计书 §4.2.2 GPU 独立池）。

首版：未接入视觉模型（YOLO/PaddleOCR）。本 worker 仅作为"独立 GPU 资源池"的占位，
说明接入方式；主链路对扫描件已用"纯文本层抽取兜底 + needs_vision 标记"降级，
不影响检索问答。

接入方式（后续迭代）：
1. 实现 knowledge/pdf_layout.detect_layout()（返回带 bbox 的区域块）
2. 实现 knowledge/ocr.OCREngine（区域级 OCR）
3. 本 worker 消费 layout 任务队列（独立于 ingest_worker），渲染页面图片 → 版面检测 → OCR
4. 回写 chunk 的 page_no/bbox，与 ingest 双写一致
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger, setup_logging

log = get_logger(__name__)


async def main() -> None:
    setup_logging()
    log.warning(
        "layout_worker.idle vision_not_configured — 主链路已用文本层抽取兜底；"
        "如需区域级 OCR，请按模块 docstring 接入 YOLO/PaddleOCR"
    )
    # 保持容器存活，便于将来挂载真实消费循环
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
