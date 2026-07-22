"""PDF 页面渲染图缓存（设计书 §4.3 页面渲染图缓存复用）。

前端溯源预览可请求单页渲染 PNG；首次渲染后缓存到对象存储，复用降低延迟与后端开销。
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.infra import object_storage

log = get_logger(__name__)


def render_page_png(data: bytes, page_no: int, *, dpi: int = 150) -> bytes:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page = doc[page_no - 1]
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def get_or_render_page(object_key: str, page_no: int, *, dpi: int = 150) -> bytes:
    """优先读对象存储缓存，未命中则渲染并回写缓存。"""
    cache_key = f"{object_key}/page-{page_no}.png"
    if object_storage.is_available():
        try:
            if object_storage.object_exists(cache_key):
                return object_storage.get_bytes(cache_key)
        except Exception as e:  # noqa: BLE001
            log.debug("render.cache_read_failed err=%s", e)

    data = object_storage.get_object_bytes(object_key)
    png = render_page_png(data, page_no, dpi=dpi)

    if object_storage.is_available():
        try:
            object_storage.store_object_bytes(cache_key, png, "image/png")
        except Exception as e:  # noqa: BLE001
            log.debug("render.cache_write_failed err=%s", e)
    return png
