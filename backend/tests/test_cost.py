"""成本管控测试：限流（本地兜底）+ embedding 缓存（Redis 不可用直通）。"""
import pytest

from app.core import ratelimit
from app.core.config import settings as cfg
from app.services.knowledge import embedding as emb
from app.services.knowledge.embedding import HashedBagEmbedding, embed_texts


@pytest.mark.asyncio
async def test_ratelimit_local_window():
    # Redis 在测试环境不可用 → 走本地滑动窗口
    assert await ratelimit.allow("rl-tenant", endpoint="rltest", limit=2, window=60) is True
    assert await ratelimit.allow("rl-tenant", endpoint="rltest", limit=2, window=60) is True
    assert await ratelimit.allow("rl-tenant", endpoint="rltest", limit=2, window=60) is False
    # 不同租户互不影响
    assert await ratelimit.allow("rl-other", endpoint="rltest", limit=2, window=60) is True


@pytest.mark.asyncio
async def test_ratelimit_unlimited(monkeypatch):
    monkeypatch.setattr(cfg, "rate_limit_chat_per_min", 0)
    for _ in range(10):
        assert await ratelimit.allow("unlim", endpoint="u") is True


@pytest.mark.asyncio
async def test_embedding_cache_passthrough(monkeypatch):
    # Redis 不可用 → embed_texts 直通 provider；默认 auto+无key → HashedBag
    monkeypatch.setattr(cfg, "embedding_provider", "auto")
    monkeypatch.setattr(cfg, "embedding_api_key", "")
    emb.reset_provider()
    vecs = await embed_texts(["hello world", "foo bar"])
    assert len(vecs) == 2 and all(isinstance(v, list) for v in vecs)
    provider = emb.get_provider()
    assert isinstance(provider, HashedBagEmbedding)
    direct = await provider.embed(["hello world", "foo bar"])
    assert vecs[0] == direct[0]
