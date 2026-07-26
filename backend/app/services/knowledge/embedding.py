"""Embedding（可插拔，设计书 §4.2.4）。

- 有 EMBEDDING_API_KEY：OpenAI 兼容接口（可指向 GLM/Qwen/DeepSeek/OpenAI）
- 无 key：HashedBagMock —— 基于词/字哈希的确定向量（仅用于跑通链路，提供 demo 级"语义"召回）
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import List

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


class EmbeddingProvider(ABC):
    dim: int

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class OpenAICompatibleEmbedding(EmbeddingProvider):
    def __init__(self, base_url: str, api_key: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        from app.core.resilience import get_breaker, retry_external

        @retry_external
        async def _call() -> List[List[float]]:
            out: List[List[float]] = []
            async with httpx.AsyncClient(timeout=60) as client:
                for i in range(0, len(texts), 32):
                    batch = texts[i : i + 32]
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    out.extend([d["embedding"] for d in data])
            return out

        # 外部调用：重试（瞬时错误）在外、熔断（持续失败快速降级）在内
        out = await get_breaker("embedding").call(_call)
        # 维度对齐校验
        if out and len(out[0]) != self.dim:
            log.warning(
                "embedding.dim_mismatch expected=%s got=%s — 请在 .env 设置 EMBEDDING_DIM 与模型一致",
                self.dim, len(out[0]),
            )
            self.dim = len(out[0])
        return out


class HashedBagEmbedding(EmbeddingProvider):
    """确定性哈希向量：相同文本→相同向量；共享 token 的查询与 chunk 会有余弦相似度。"""

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> List[float]:
        v = [0.0] * self.dim
        for tok in _TOKEN_RE.findall((text or "").lower()):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return v

    async def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]


class LocalSentenceTransformerEmbedding(EmbeddingProvider):
    """本地 sentence-transformers 向量化（私有化/离线场景）。

    首次调用懒加载模型（CPU/GPU 自动）；dim 取自模型。
    注意：Milvus collection 用 settings.embedding_dim 创建，需与本模型 dim 一致。
    """

    def __init__(self, model_name: str, dim: int):
        self.model_name = model_name
        self.dim = dim
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            real_dim = self._model.get_sentence_embedding_dimension()
            if real_dim != self.dim:
                log.warning(
                    "embedding.st.dim_mismatch model_dim=%s config_dim=%s — 请在 .env 设 EMBEDDING_DIM=%s",
                    real_dim, self.dim, real_dim,
                )
                self.dim = real_dim
        return self._model

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import asyncio

        model = await asyncio.to_thread(self._load)
        embs = await asyncio.to_thread(lambda: model.encode(texts, show_progress_bar=False))
        return [list(map(float, e)) for e in embs]


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider
    provider = (settings.embedding_provider or "auto").lower()
    if provider == "sentence_transformers":
        log.info("embedding.provider=sentence_transformers model=%s", settings.embedding_local_model)
        _provider = LocalSentenceTransformerEmbedding(settings.embedding_local_model, settings.embedding_dim)
    elif provider == "mock":
        log.warning("embedding.provider=mock_hashedbag (强制 mock)")
        _provider = HashedBagEmbedding(dim=settings.embedding_dim)
    elif provider == "openai_compatible" or (provider == "auto" and settings.embedding_api_key):
        log.info("embedding.provider=openai_compatible model=%s", settings.embedding_model)
        _provider = OpenAICompatibleEmbedding(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    else:
        log.warning("embedding.provider=mock_hashedbag (无 EMBEDDING_API_KEY，仅跑通链路)")
        _provider = HashedBagEmbedding(dim=settings.embedding_dim)
    return _provider


def reset_provider() -> None:
    """测试用：重置单例。"""
    global _provider
    _provider = None


def _cache_prefix() -> str:
    model = settings.embedding_model or settings.embedding_local_model
    return f"emb:{settings.embedding_provider}:{model}:{settings.embedding_dim}"


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """带 Redis 缓存的批量向量化（按文本内容缓存，写入与查询复用）。

    缓存命中/未命中计入指标；Redis 不可用则直通 provider。
    """
    from app.core.metrics import EMBEDDING_CACHE
    from app.infra import redis_store

    provider = get_provider()
    if (
        not texts
        or not settings.embedding_cache_enabled
        or not redis_store.is_available()
    ):
        return await provider.embed(texts)

    import hashlib

    prefix = _cache_prefix()
    keys = [f"{prefix}:{hashlib.sha256(t.encode('utf-8')).hexdigest()[:24]}" for t in texts]
    cached = await redis_store.cache_mget(keys)

    out: List[Optional[List[float]]] = [None] * len(texts)
    miss_idx: List[int] = [i for i, c in enumerate(cached) if c is None]
    hits = len(texts) - len(miss_idx)
    EMBEDDING_CACHE.labels(result="hit").inc(hits)
    for i, c in enumerate(cached):
        if c is not None:
            out[i] = c

    if miss_idx:
        miss_texts = [texts[i] for i in miss_idx]
        embs = await provider.embed(miss_texts)
        EMBEDDING_CACHE.labels(result="miss").inc(len(miss_idx))
        mapping = {keys[i]: embs[j] for j, i in enumerate(miss_idx)}
        await redis_store.cache_mset(mapping, ttl=settings.embedding_cache_ttl)
        for j, i in enumerate(miss_idx):
            out[i] = embs[j]
    return out  # type: ignore[return-value]
