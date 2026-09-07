import math

import pytest

from app.services.knowledge.embedding import HashedBagEmbedding, OpenAICompatibleEmbedding


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-12)


def test_dim_and_deterministic():
    emb = HashedBagEmbedding(dim=256)
    a = emb._vec("hello world")
    b = emb._vec("hello world")
    assert len(a) == 256
    assert a == b


def test_shared_tokens_positive_similarity():
    # 用较大 dim 避免哈希桶碰撞（mock 固有特性），从而验证"共享 token 提升相似度"
    emb = HashedBagEmbedding(dim=4096)
    v_q = emb._vec("apple banana")
    v_chunk = emb._vec("apple orange")
    v_unrelated = emb._vec("zzz qqq")
    assert _cos(v_q, v_chunk) > 0.0           # 共享 apple
    assert _cos(v_q, v_chunk) > _cos(v_q, v_unrelated)


def test_async_embed():
    import asyncio

    emb = HashedBagEmbedding(dim=128)
    vecs = asyncio.run(emb.embed(["a b", "c d"]))
    assert len(vecs) == 2 and len(vecs[0]) == 128


@pytest.mark.asyncio
async def test_openai_compatible_batches_by_batch_size(monkeypatch):
    # qwen3.7-text-embedding 上限 20/批：45 条应分 3 批（20+20+5），不能整批发
    from app.services.knowledge import embedding as emb_mod

    calls = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"embedding": [0.1]} for _ in calls[-1]]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append(kw["json"]["input"])
            return _Resp()

    monkeypatch.setattr(emb_mod.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(emb_mod.settings, "embedding_batch_size", 20)

    p = OpenAICompatibleEmbedding("http://x/v1", "k", "qwen3.7-text-embedding", 1)
    out = await p.embed([f"t{i}" for i in range(45)])
    assert [len(c) for c in calls] == [20, 20, 5]
    assert len(out) == 45
