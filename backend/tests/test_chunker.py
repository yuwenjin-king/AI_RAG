from app.services.knowledge import chunker
from app.services.knowledge.block import Block, ParsedDoc


def test_chunk_small_blocks_preserve_page_and_bbox():
    parsed = ParsedDoc(
        title="t",
        blocks=[
            Block(text="alpha", page_no=1, bbox=[0.1, 0.1, 0.2, 0.2]),
            Block(text="beta", page_no=1, bbox=[0.3, 0.3, 0.4, 0.4]),
            Block(text="gamma", page_no=2, bbox=[0.5, 0.5, 0.6, 0.6]),
        ],
    )
    chunks = chunker.chunk_document(parsed, max_size=800)
    assert len(chunks) == 3
    assert [c["page_no"] for c in chunks] == [1, 1, 2]
    assert chunks[0]["bbox"] == [0.1, 0.1, 0.2, 0.2]
    assert [c["ordinal"] for c in chunks] == [0, 1, 2]


def test_chunk_large_block_splits_with_overlap():
    big = "word " * 500  # 远超 max_size
    parsed = ParsedDoc(title="t", blocks=[Block(text=big, page_no=5, bbox=[0.0, 0.0, 1.0, 1.0])])
    chunks = chunker.chunk_document(parsed, max_size=100, overlap=20)
    assert len(chunks) > 1
    # 每片仍携带原始页码与 bbox（溯源不丢）
    assert all(c["page_no"] == 5 for c in chunks)
    assert all(c["bbox"] == [0.0, 0.0, 1.0, 1.0] for c in chunks)


def test_chunk_empty_doc():
    parsed = ParsedDoc(title="t", blocks=[])
    assert chunker.chunk_document(parsed) == []
