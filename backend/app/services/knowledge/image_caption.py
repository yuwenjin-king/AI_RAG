"""图片 caption hook（plan_three §4 多模态）。

图片区域此前无文字描述，图表/示意图类问题召回差。本 hook 给图片区生成 caption
Block(kind="image_caption")，并入索引。

- 默认关 / 无 VLM key → NoOp，返回 None（图片区无 caption，沿用旧行为，不阻断解析）
- image_caption_enabled + llm key → 调 OpenAI 兼容 vision 接口（如 glm-4v）生成 caption

仿 ocr.py / tables.py：懒探测 + 不可用降级。接入点：vision.extract_with_vision
处理扫描件图片 block 时调用（文本层 PDF 的图片区由版面检测标记后同样可调用）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.knowledge.block import Block

log = get_logger(__name__)


class CaptionEngine(ABC):
    name: str = "base"

    @abstractmethod
    def caption(self, image_bytes: bytes, page_no: int, hint: str = "") -> Optional[str]:
        ...


class NoOpCaption(CaptionEngine):
    name = "none"

    def caption(self, image_bytes: bytes, page_no: int, hint: str = "") -> Optional[str]:  # noqa: D401
        return None


class VLMCaption(CaptionEngine):
    """OpenAI 兼容 vision 接口生成 caption。未启用/无 key/失败 → None。"""

    name = "vlm"

    def caption(self, image_bytes: bytes, page_no: int, hint: str = "") -> Optional[str]:
        if not settings.image_caption_enabled:
            return None
        if not (settings.llm_base_url and settings.llm_api_key):
            return None
        try:
            import base64

            import httpx

            data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
            prompt = hint or "请用中文简洁描述这张图片的关键信息（图表/示意图/照片），便于检索。"
            resp = httpx.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.image_caption_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                },
                timeout=settings.llm_timeout,
            )
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            content = (content or "").strip()
            return content or None
        except Exception as e:  # noqa: BLE001
            log.warning("image_caption.vlm.failed err=%s", e)
            return None


_engine: Optional[CaptionEngine] = None


def get_caption_engine() -> CaptionEngine:
    """单例：image_caption_enabled → VLMCaption，否则 NoOp。"""
    global _engine
    if _engine is not None:
        return _engine
    _engine = VLMCaption() if settings.image_caption_enabled else NoOpCaption()
    log.info("image_caption.engine=%s", _engine.name)
    return _engine


def reset_caption_engine() -> None:
    """测试用：重置单例。"""
    global _engine
    _engine = None


def caption_to_block(
    image_bytes: bytes, page_no: int, bbox: Optional[list] = None, hint: str = ""
) -> Optional[Block]:
    """生成图片 caption Block；无 caption → None（调用方跳过）。"""
    cap = get_caption_engine().caption(image_bytes, page_no, hint)
    if not cap:
        return None
    return Block(text=cap, page_no=page_no, bbox=bbox, kind="image_caption", extra={"caption": cap})
