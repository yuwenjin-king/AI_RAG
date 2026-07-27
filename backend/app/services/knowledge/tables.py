"""PDF 表格抽取与序列化（plan_three §4 多模态）。

表格此前被拍平成文本（行列关系丢失），表格类问题（"Q3 营收"）召回/溯源差。
本模块：
- 抽取：pdfplumber（轻量、纯 Python，首选）/ camelot（需 ghostscript，可选）—— 仿 ocr.py 模式懒导入 + 不可用降级为 NoOp。
- 序列化（纯函数，离线可测）：表格 → Markdown/HTML/纯文本，保留行列结构；行感知切分防超长。
- 入索引：extract_table_blocks → Block(kind="table", text=markdown, extra={headers,nrows,ncols,html,caption})，
  page_no/bbox 保留 → 经 pdf_layout 注入 → chunker/embed/Milvus+OpenSearch 自动流转（见 ingest._index_blocks）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.knowledge.block import Block

log = get_logger(__name__)


@dataclass
class ExtractedTable:
    """已抽取的表格（行列结构 + 区域溯源）。"""

    page_no: int
    rows: List[List[str]] = field(default_factory=list)        # 每行单元格文本
    headers: Optional[List[str]] = None                         # None → 首行作表头
    bbox: Optional[List[float]] = None                          # 归一化 [x0,y0,x1,y1]
    caption: Optional[str] = None


# ===== 纯序列化（离线单测重点） =====
def _clean_cell(s: str) -> str:
    """单元格清洗：去首尾空白、折叠内部换行/多空格。"""
    if s is None:
        return ""
    return " ".join(str(s).replace("\n", " ").replace("\r", " ").split())


def _normalize_rows(rows: List[List[str]]) -> List[List[str]]:
    """补齐参差行到等宽，清洗每个单元格。"""
    cleaned = [[_clean_cell(c) for c in row] for row in rows if row is not None]
    width = max((len(r) for r in cleaned), default=0)
    if width == 0:
        return []
    return [r + [""] * (width - len(r)) for r in cleaned]


def _split_headers(rows: List[List[str]], headers: Optional[List[str]]) -> tuple[List[str], List[List[str]]]:
    """确定表头与数据行：显式 headers 优先；否则首行作表头。"""
    if headers:
        return [_clean_cell(h) for h in headers], rows
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _escape_md_cell(s: str) -> str:
    """转义 Markdown 表格分隔符（| 与换行）。"""
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def table_to_markdown(rows: List[List[str]], headers: Optional[List[str]] = None) -> str:
    """GitHub-flavored Markdown 表（保留行列）。空表 → ""。"""
    rows = _normalize_rows(rows)
    header, body = _split_headers(rows, headers)
    if not header and not body:
        return ""
    cols = _normalize_rows([header] if header else body[:1])
    width = len(cols[0]) if cols else 0
    if width == 0:
        return ""
    head_cells = [(_escape_md_cell(header[i]) if i < len(header) else "") for i in range(width)]
    lines = ["| " + " | ".join(head_cells) + " |", "|" + "|".join([" --- "] * width) + "|"]
    for row in body:
        cells = [_escape_md_cell(row[i]) if i < len(row) else "" for i in range(width)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def table_to_html(rows: List[List[str]], headers: Optional[List[str]] = None) -> str:
    """HTML 表（前端表格高亮用）。"""
    rows = _normalize_rows(rows)
    header, body = _split_headers(rows, headers)
    if not header and not body:
        return ""
    cols = _normalize_rows([header] if header else body[:1])
    width = len(cols[0]) if cols else 0
    if width == 0:
        return ""
    from html import escape

    def _cells(row: List[str], tag: str) -> str:
        return "".join(f"<{tag}>{escape(row[i] if i < len(row) else '')}</{tag}>" for i in range(width))

    head = "".join(f"<th>{escape(header[i] if i < len(header) else '')}</th>" for i in range(width))
    body_html = "".join(f"<tr>{_cells(r, 'td')}</tr>" for r in body)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body_html}</tbody></table>"


def table_to_text(rows: List[List[str]], headers: Optional[List[str]] = None) -> str:
    """纯文本兜底（" | "分隔），供需要扁平文本的场景。"""
    rows = _normalize_rows(rows)
    header, body = _split_headers(rows, headers)
    lines = []
    if header:
        lines.append(" | ".join(header))
        lines.append(" | ".join("-" * max(1, len(h)) for h in header))
    for row in body:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def split_markdown_table(md: str, max_size: int = 800) -> List[str]:
    """行感知切分 Markdown 表：超长时按数据行分组，每片**重复表头**，保持结构完整。

    避免 fixed_length 把表格从行中间切断（丢行列关系）。
    """
    md = (md or "").strip()
    if not md:
        return []
    if len(md) <= max_size:
        return [md]

    lines = md.splitlines()
    # 定位表头：首个 | 开头行 + 紧随的分隔行
    header_idx = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("|")), None)
    if header_idx is None or header_idx + 1 >= len(lines):
        return [md]  # 非 markdown 表格式 → 退回整体（调用方应保证传入 markdown）
    header_block = "\n".join(lines[header_idx : header_idx + 2])
    data_lines = [ln for ln in lines[header_idx + 2 :] if ln.strip()]
    if not data_lines:
        return [header_block]

    pieces: List[str] = []
    cur = header_block
    for ln in data_lines:
        candidate = cur + "\n" + ln
        if len(candidate) > max_size and cur != header_block:
            pieces.append(cur)
            cur = header_block + "\n" + ln
        else:
            cur = candidate
    pieces.append(cur)
    return pieces


# ===== 抽取器（仿 ocr.py：懒导入 + 不可用降级） =====
class TableExtractor(ABC):
    name: str = "base"

    @abstractmethod
    def extract(self, data: bytes) -> List[ExtractedTable]:
        ...


class NoOpTableExtractor(TableExtractor):
    name = "none"

    def extract(self, data: bytes) -> List[ExtractedTable]:  # noqa: D401
        return []


class PdfplumberExtractor(TableExtractor):
    """pdfplumber 表格抽取（纯 Python，首选）。不可用/失败 → []。"""

    name = "pdfplumber"

    def extract(self, data: bytes) -> List[ExtractedTable]:
        try:
            import pdfplumber
        except Exception as e:  # noqa: BLE001
            log.info("tables.pdfplumber.unavailable err=%s", e)
            return []
        out: List[ExtractedTable] = []
        try:
            with pdfplumber.open(stream=data) as pdf:
                for page_no, page in enumerate(pdf.pages, start=1):
                    try:
                        w, h = float(page.width), float(page.height)
                    except Exception:  # noqa: BLE001
                        w = h = 0.0
                    found = page.find_tables()
                    tables = page.extract_tables() or []
                    for idx, rows in enumerate(tables):
                        if not rows:
                            continue
                        bbox = None
                        if idx < len(found) and w > 0 and h > 0:
                            try:
                                x0, y0, x1, y1 = found[idx].bbox
                                bbox = [
                                    max(0.0, min(1.0, x0 / w)),
                                    max(0.0, min(1.0, y0 / h)),
                                    max(0.0, min(1.0, x1 / w)),
                                    max(0.0, min(1.0, y1 / h)),
                                ]
                            except Exception:  # noqa: BLE001
                                bbox = None
                        out.append(ExtractedTable(page_no=page_no, rows=rows, bbox=bbox))
        except Exception as e:  # noqa: BLE001
            log.warning("tables.pdfplumber.failed err=%s", e)
        return out


class CamelotExtractor(TableExtractor):
    """camelot 表格抽取（lattice/stream，需 ghostscript）。不可用/失败 → []。"""

    name = "camelot"

    def extract(self, data: bytes) -> List[ExtractedTable]:
        try:
            import camelot
            import tempfile
            import os
        except Exception as e:  # noqa: BLE001
            log.info("tables.camelot.unavailable err=%s", e)
            return []
        out: List[ExtractedTable] = []
        tmp_path = None
        try:
            # camelot 需文件路径，写临时文件
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            tables = camelot.read_pdf(tmp_path, pages="all")
            for t in tables:
                rows = t.df.values.tolist()
                out.append(ExtractedTable(page_no=int(t.page), rows=rows, bbox=None))
        except Exception as e:  # noqa: BLE001
            log.warning("tables.camelot.failed err=%s", e)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:  # noqa: BLE001
                    pass
        return out


_extractor: Optional[TableExtractor] = None


def get_table_extractor() -> TableExtractor:
    """按 settings.table_extractor 选择（auto|pdfplumber|camelot|none）。单例。"""
    global _extractor
    if _extractor is not None:
        return _extractor
    mode = (settings.table_extractor or "auto").lower()
    if mode == "pdfplumber":
        _extractor = PdfplumberExtractor()
    elif mode == "camelot":
        _extractor = CamelotExtractor()
    elif mode == "none":
        _extractor = NoOpTableExtractor()
    else:  # auto：探测可用性
        _extractor = PdfplumberExtractor() if _can_import("pdfplumber") else NoOpTableExtractor()
    log.info("tables.extractor=%s", _extractor.name)
    return _extractor


def _can_import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def reset_extractor() -> None:
    """测试用：重置单例。"""
    global _extractor
    _extractor = None


def extract_table_blocks(data: bytes) -> List[Block]:
    """抽取表格并转为 Block(kind="table")。未启用/不可用 → []。"""
    if not settings.table_extraction_enabled:
        return []
    tables = get_table_extractor().extract(data)
    blocks: List[Block] = []
    for t in tables:
        rows = _normalize_rows(t.rows)
        if not rows:
            continue
        md = table_to_markdown(rows, headers=t.headers)
        if not md.strip():
            continue
        text = f"{t.caption}\n\n{md}" if t.caption else md
        blocks.append(
            Block(
                text=text,
                page_no=t.page_no,
                bbox=t.bbox,
                kind="table",
                extra={
                    "headers": t.headers or rows[0],
                    "nrows": len(rows),
                    "ncols": len(rows[0]) if rows else 0,
                    "html": table_to_html(rows, headers=t.headers),
                    "caption": t.caption,
                    "extractor": get_table_extractor().name,
                },
            )
        )
    log.info("tables.extracted blocks=%s", len(blocks))
    return blocks
