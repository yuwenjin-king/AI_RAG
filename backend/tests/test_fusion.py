from app.services.retrieval.fusion import mmr_select, rrf_fuse


def _hit(cid, score=1.0, content=""):
    return {"chunk_id": cid, "doc_id": 1, "score": score, "content": content}


def test_rrf_dedup_and_rank():
    vec = [_hit(1), _hit(2), _hit(3)]          # 排名 1,2,3
    kw = [_hit(3), _hit(2), _hit(4)]           # 排名 1,2,3
    fused = rrf_fuse(vec, kw, k=60)
    ids = [f["chunk_id"] for f in fused]
    # 去重：4 个唯一 chunk
    assert sorted(ids) == [1, 2, 3, 4]
    # chunk 2 与 3 在两路都靠前 → RRF 分更高，应排在 1 与 4 之前
    assert ids.index(2) < ids.index(1)
    assert ids.index(3) < ids.index(1)
    assert ids.index(3) < ids.index(4)


def test_rrf_empty():
    assert rrf_fuse([], []) == []


def test_mmr_truncates_and_diversifies():
    cands = [
        _hit(1, content="alpha beta"),
        _hit(2, content="alpha beta"),   # 与 1 高度重叠
        _hit(3, content="gamma delta"),
    ]
    out = mmr_select(cands, top_n=2, lambda_=0.5)
    assert len(out) == 2
    # 高度重叠的两条不应同时入选（多样性）
    out_contents = {c["content"] for c in out}
    assert out_contents != {"alpha beta"}
