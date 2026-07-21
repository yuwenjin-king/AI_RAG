"""重排序（Cross-Encoder，可插拔，设计书 §4.4.3）。

无 RERANK_API_KEY → NoOp（直接返回 RRF 顺序），orchestrator 据此降级。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Reranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: List[dict], top_n: int) -> List[dict]:
        ...


class NoOpReranker(Reranker):
    async def rerank(self, query: str, candidates: List[dict], top_n: int) -> List[dict]:
        return candidates[:top_n]


class CrossEncoderReranker(Reranker):
    """OpenAI 兼容 / Cohere-Jina 风格的 /rerank 接口。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def rerank(self, query: str, candidates: List[dict], top_n: int) -> List[dict]:
        if not candidates:
            return []
        documents = [c.get("content", "") for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/rerank",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "query": query, "documents": documents, "top_n": top_n},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
        except Exception as e:  # noqa: BLE001
            log.warning("rerank.failed degraded_keep_rrf err=%s", e)
            return candidates[:top_n]
        out: List[dict] = []
        for r in results:
            idx = r.get("index")
            if idx is None or idx >= len(candidates):
                continue
            item = dict(candidates[idx])
            item["score"] = float(r.get("relevance_score", 0.0))
            item["source"] = "reranked"
            out.append(item)
        return out


_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is not None:
        return _reranker
    if settings.rerank_api_key and settings.rerank_base_url:
        log.info("reranker=cross_encoder model=%s", settings.rerank_model)
        _reranker = CrossEncoderReranker(
            settings.rerank_base_url, settings.rerank_api_key, settings.rerank_model
        )
    else:
        _reranker = NoOpReranker()
    return _reranker
