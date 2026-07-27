"""多模态表格抽取测试（plan_three §4）。

纯序列化 + 行感知切分（离线重点）+ chunker 表格感知 + 抽取器/caption 不可用降级
（不触真实 pdfplumber/camelot/VLM）。
"""
from __future__ import annotations

from app.services.knowledge import image_caption, tables
from app.services.knowledge.block import Block, ParsedDoc
from app.services.knowledge import chunker


# ===== 纯序列化 =====
def test_table_to_markdown_with_headers():
    md = tables.table_to_markdown([["1", "2"], ["Q3", "100"]], headers=["季度", "营收"])
    lines = md.splitlines()
    assert lines[0] == "| 季度 | 营收 |"
    assert lines[1].startswith("|") and "---" in lines[1]
    assert lines[2] == "| 1 | 2 |"
    assert lines[3] == "| Q3 | 100 |"


def test_table_to_markdown_first_row_as_header():
    md = tables.table_to_markdown([["季度", "营收"], ["Q3", "100"]])
    assert md.splitlines()[0] == "| 季度 | 营收 |"


def test_table_to_markdown_escapes_pipes_and_pads_ragged():
    md = tables.table_to_markdown([["a", "b|c", "d"], ["x", "y"]], headers=["h1", "h2", "h3"])
    lines = md.splitlines()
    assert lines[2] == "| a | b\\|c | d |"  # 单元格中的 | 转义为 \|
    assert lines[3] == "| x | y |  |"       # 参差行补齐到等宽


def test_table_to_markdown_empty():
    assert tables.table_to_markdown([]) == ""
    assert tables.table_to_markdown([[]]) == ""


def test_table_to_html_structure():
    html = tables.table_to_html([["1"]], headers=["h"])
    assert html.startswith("<table>") and "</table>" in html
    assert "<th>h</th>" in html and "<td>1</td>" in html


def test_table_to_text_basic():
    txt = tables.table_to_text([["Q3", "100"]], headers=["季度", "营收"])
    assert "季度 | 营收" in txt and "Q3 | 100" in txt


# ===== 行感知切分 =====
def test_split_markdown_table_under_limit_returns_whole():
    md = tables.table_to_markdown([["a"]], headers=["h"])
    assert tables.split_markdown_table(md, max_size=800) == [md]


def test_split_markdown_table_splits_by_row_repeating_header():
    rows = [["v" * 50] for _ in range(20)]
    md = tables.table_to_markdown(rows, headers=["h"])
    pieces = tables.split_markdown_table(md, max_size=200)
    assert len(pieces) > 1
    # 每片都含表头行 + 分隔行（结构完整）
    for p in pieces:
        pl = p.splitlines()
        assert pl[0] == "| h |" and "---" in pl[1]


# ===== chunker 表格感知 =====
def test_chunk_document_keeps_table_intact():
    md = tables.table_to_markdown([["a"], ["b"]], headers=["h"])
    parsed = ParsedDoc(title="t", blocks=[Block(text=md, page_no=1, bbox=[0.1, 0.2, 0.3, 0.4], kind="table")])
    chunks = chunker.chunk_document(parsed, max_size=800)
    assert len(chunks) == 1
    assert chunks[0]["content"] == md
    assert chunks[0]["extra"]["kind"] == "table"
    assert chunks[0]["bbox"] == [0.1, 0.2, 0.3, 0.4]  # 溯源保留


def test_chunk_document_table_row_split_when_huge():
    rows = [["v" * 50] for _ in range(20)]
    md = tables.table_to_markdown(rows, headers=["h"])
    parsed = ParsedDoc(title="t", blocks=[Block(text=md, page_no=2, kind="table")])
    chunks = chunker.chunk_document(parsed, max_size=200)
    assert len(chunks) > 1
    assert all(c["extra"]["kind"] == "table" for c in chunks)


def test_chunk_document_text_unchanged():
    # 非 table block 行为不变
    parsed = ParsedDoc(title="t", blocks=[Block(text="普通文本", page_no=1)])
    chunks = chunker.chunk_document(parsed)
    assert len(chunks) == 1 and chunks[0]["extra"]["kind"] == "text"


def test_parent_child_table_is_atomic_parent_with_children():
    md = tables.table_to_markdown([["a"], ["b"]], headers=["h"])
    parsed = ParsedDoc(
        title="t",
        blocks=[
            Block(text="前言文本", page_no=1),
            Block(text=md, page_no=1, kind="table"),
            Block(text="后记文本", page_no=1),
        ],
    )
    out = chunker.chunk_document_parent_child(parsed, parent_size=1500, child_size=400)
    # 表格自成父块，不与前后文本聚合
    parents = [c for c in out if c["level"] == "parent"]
    table_parent = next(p for p in parents if p["extra"].get("kind") == "table")
    assert table_parent["content"] == md
    # 文本父块不含表格内容
    text_parents = [p for p in parents if p["extra"].get("kind") == "text"]
    assert all("前言文本" not in p["content"] or md not in p["content"] for p in text_parents)
    # 表格父块有对应子块（参与检索索引）
    table_children = [c for c in out if c["level"] == "child" and c["parent_key"] == table_parent["parent_key"]]
    assert table_children and table_children[0]["content"] == md


# ===== 抽取器不可用降级（不触真实 pdfplumber/camelot） =====
def test_noop_extractor_returns_empty():
    assert tables.NoOpTableExtractor().extract(b"") == []


def test_pdfplumber_extractor_degrades_when_absent():
    # 本机未装 pdfplumber → import 失败 → []（不抛异常）
    assert tables.PdfplumberExtractor().extract(b"not-a-pdf") == []


def test_get_table_extractor_none_mode(monkeypatch):
    monkeypatch.setattr(tables.settings, "table_extractor", "none")
    tables.reset_extractor()
    assert tables.get_table_extractor().name == "none"
    tables.reset_extractor()


def test_extract_table_blocks_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(tables.settings, "table_extraction_enabled", False)
    tables.reset_extractor()
    assert tables.extract_table_blocks(b"") == []


def test_extract_table_blocks_produces_table_block(monkeypatch):
    monkeypatch.setattr(tables.settings, "table_extraction_enabled", True)
    monkeypatch.setattr(tables.settings, "table_extractor", "none")
    tables.reset_extractor()

    # 替换抽取器为返回合成表格的假实现
    class _Fake(tables.TableExtractor):
        name = "fake"

        def extract(self, data):
            return [tables.ExtractedTable(page_no=1, rows=[["季度", "营收"], ["Q3", "100"]], bbox=[0.1, 0.1, 0.9, 0.2])]

    monkeypatch.setattr(tables, "get_table_extractor", lambda: _Fake())
    blocks = tables.extract_table_blocks(b"")
    assert len(blocks) == 1
    b = blocks[0]
    assert b.kind == "table"
    assert "| 季度 | 营收 |" in b.text and "Q3" in b.text
    assert b.page_no == 1 and b.bbox == [0.1, 0.1, 0.9, 0.2]
    assert b.extra["nrows"] == 2 and b.extra["ncols"] == 2
    assert "<table>" in b.extra["html"]
    tables.reset_extractor()


# ===== 图片 caption 不可用降级（不触真实 VLM） =====
def test_caption_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(image_caption.settings, "image_caption_enabled", False)
    image_caption.reset_caption_engine()
    assert image_caption.get_caption_engine().caption(b"img", 1) is None
    assert image_caption.caption_to_block(b"img", 1) is None
    image_caption.reset_caption_engine()


def test_caption_vlm_no_key_degrades(monkeypatch):
    # 启用但无 llm_api_key → 降级 None
    monkeypatch.setattr(image_caption.settings, "image_caption_enabled", True)
    monkeypatch.setattr(image_caption.settings, "llm_api_key", "")
    image_caption.reset_caption_engine()
    assert image_caption.get_caption_engine().caption(b"img", 1) is None
    image_caption.reset_caption_engine()
