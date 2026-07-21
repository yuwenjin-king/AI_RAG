from app.services.ingestion.parser import parse


def test_parse_text():
    doc = parse(b"hello world\nsecond line", "text/plain", "note.txt")
    assert doc.title.startswith("hello")
    assert len(doc.blocks) == 1
    assert "hello world" in doc.blocks[0].text


def test_parse_html_strips_tags():
    doc = parse(b"<p>hi <b>there</b></p>", "text/html", "x.html")
    assert "hi" in doc.blocks[0].text and "there" in doc.blocks[0].text
    assert "<" not in doc.blocks[0].text


def test_parse_empty():
    doc = parse(b"", "text/plain", "empty.txt")
    assert doc.blocks == []
