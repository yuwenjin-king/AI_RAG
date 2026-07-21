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


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider
    if settings.embedding_api_key:
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
