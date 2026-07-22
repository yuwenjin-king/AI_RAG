"""覆盖补充：Milvus 过滤表达式构造 + 内置 BM25。"""
from app.infra.milvus_store import build_filter
from app.services.retrieval.bm25_local import BM25


def test_build_filter_tenant_only():
    assert build_filter("acme") == 'tenant_id == "acme"'


def test_build_filter_kb_and_doc_whitelists():
    f = build_filter("acme", knowledge_base_id=3, kb_ids=[1, 2], doc_ids=[10, 20])
    assert 'tenant_id == "acme"' in f
    assert "kb_id == 3" in f
    assert "kb_id in [1,2]" in f
    assert "doc_id in [10,20]" in f


def test_build_filter_escapes_quotes_and_ints():
    # tenant 双引号转义防注入；id 强制 int（字符串数字也安全）
    f = build_filter('a"x', kb_ids=["7", "8"])
    assert f == 'tenant_id == "ax" and kb_id in [7,8]'


def test_bm25_ranking():
    corpus = [
        "apple apple banana".split(),
        "apple cherry".split(),
        "delta echo".split(),
    ]
    bm = BM25(corpus)
    scores = bm.get_scores(["apple"])
    # doc0（apple×2）> doc1（apple×1）> doc2（无）
    assert scores[0] > scores[1] > scores[2]
    assert scores[2] == 0.0


def test_bm25_empty_and_missing_term():
    bm = BM25([])
    assert bm.get_scores(["x"]) == []
    bm2 = BM25([["a", "b"], ["c"]])
    s = bm2.get_scores(["zzz"])
    assert all(v == 0.0 for v in s)
