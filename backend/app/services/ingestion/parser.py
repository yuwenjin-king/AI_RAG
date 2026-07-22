"""文档解析路由（设计书 §4.2.1）：按类型分流到专用解析器，统一输出 ParsedDoc。

支持：PDF（文本层 + bbox）、纯文本/Markdown/代码（单块）、HTML（去标签）。
其余类型（Office 等）首版 stub：尝试纯文本兜底并标记。
"""
from __future__ import annotations

import re

from app.core.logging import get_logger
from app.services.ingestion import pii
from app.services.knowledge import pdf_layout
from app.services.knowledge.block import Block, ParsedDoc

log = get_logger(__name__)

_TEXT_LIKE = {
    "text/plain", "text/markdown", "text/csv", "application/json",
    "text/x-python", "application/x-yaml", "text/yaml",
}


def _guess_kind(content_type: str, filename: str = "") -> str:
    ct = (content_type or "").lower()
    name = (filename or "").lower()
    if ct == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if "html" in ct or name.endswith((".html", ".htm")):
        return "html"
    if ct in _TEXT_LIKE or any(name.endswith(ext) for ext in (".txt", ".md", ".csv", ".json", ".py", ".yaml", ".yml", ".log", ".js", ".ts", ".java", ".go", ".rs", ".sql")):
        return "text"
    return "unknown"


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s[:120]
    return "untitled"


_TAG_RE = re.compile(r"<[^>]+>")


def parse(data: bytes, content_type: str = "", filename: str = "") -> ParsedDoc:
    kind = _guess_kind(content_type, filename)
    title = filename or "document"
    needs_vision = False

    if kind == "pdf":
        blocks, needs_vision = pdf_layout.extract_blocks(data)
        text_head = " ".join(b.text for b in blocks[:5])
        title = _title_from_text(text_head) if text_head else title
        if needs_vision:
            vision = pdf_layout.detect_layout(data)
            if vision:
                blocks = vision
                needs_vision = False
        return pii.mask_doc(ParsedDoc(title=title, blocks=blocks, needs_vision=needs_vision, meta={"kind": "pdf", "pages_hint": len({b.page_no for b in blocks})}))

    # 文本类 / HTML / 未知（尝试 utf-8 兜底）
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        text = ""
    if kind == "html":
        text = _TAG_RE.sub(" ", text)
    blocks = [Block(text=text)] if text.strip() else []
    title = _title_from_text(text) if text.strip() else title
    return pii.mask_doc(ParsedDoc(title=title, blocks=blocks, needs_vision=False, meta={"kind": kind}))
