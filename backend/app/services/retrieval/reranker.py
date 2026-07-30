"""重排序（Cross-Encoder，可插拔，设计书 §4.4.3）。

按 `rerank_provider` 选择实现，均失败时降级为保留 RRF 顺序（精排是可选增强）：
- `cross_encoder`：OpenAI 兼容 / Cohere-Jina 风格的 `/rerank` 接口
- `dashscope`：阿里云 DashScope / 百炼 原生 rerank（gte-rerank-v2；兼容模式无 /rerank）
- `local`：本地 FlagEmbedding（BAAI/bge-reranker-v2-m3 等，自托管，无外部 API）
- `auto`（默认）：base_url 含 aliyuncs→dashscope；否则有 base_url+key→cross_encoder

无配置 → NoOp（直接返回 RRF 顺序），orchestrator 据此降级。
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
    """Cohere/Jina 风格的 /rerank 接口（OpenAI 兼容 provider 若提供该端点）。"""

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
            log.warning("rerank.cross_encoder.failed degraded_keep_rrf err=%s", e)
            return candidates[:top_n]
        return _order_by_results(candidates, results, top_n)


class DashScopeReranker(Reranker):
    """阿里云 DashScope / 百炼 原生 rerank（gte-rerank 系列）。

    compatible-mode 无 `/rerank`（OpenAI 无此接口，实测 404），走原生
    `{host}/api/v1/services/rerank/text-rerank/text-rerank`，请求体 input.{query,documents}。
    base_url 给兼容模式 URL（含 /compatible-mode/v1）也行——自动剥成 host。
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        host = base_url.split("/compatible-mode")[0].rstrip("/")
        self.endpoint = f"{host}/api/v1/services/rerank/text-rerank/text-rerank"
        self.api_key = api_key
        self.model = model

    async def rerank(self, query: str, candidates: List[dict], top_n: int) -> List[dict]:
        if not candidates:
            return []
        documents = [c.get("content", "") for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "input": {"query": query, "documents": documents},
                        "parameters": {"top_n": top_n, "return_documents": False},
                    },
                )
                resp.raise_for_status()
                results = resp.json().get("output", {}).get("results", [])
        except Exception as e:  # noqa: BLE001
            log.warning("rerank.dashscope.failed degraded_keep_rrf err=%s", e)
            return candidates[:top_n]
        return _order_by_results(candidates, results, top_n)


class LocalFlagReranker(Reranker):
    """本地 BGE reranker（FlagEmbedding）：BAAI/bge-reranker-v2-m3 等自托管模型。

    首次调用懒加载（CPU/GPU 自动），与 LocalSentenceTransformerEmbedding 同模式。
    模型体积大 + 依赖 torch/transformers，放可选 extra（pip install -e .[rerank]）。
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            import asyncio  # noqa: F401  (仅标注 to_thread 内可同步用)

            from FlagEmbedding import FlagReranker

            try:
                import torch

                use_fp16 = torch.cuda.is_available()
            except Exception:  # noqa: BLE001
                use_fp16 = False
            self._model = FlagReranker(self.model_name, use_fp16=use_fp16)
            log.info("reranker.local.loaded model=%s fp16=%s", self.model_name, use_fp16)
        return self._model

    async def rerank(self, query: str, candidates: List[dict], top_n: int) -> List[dict]:
        if not candidates:
            return []
        import asyncio

        try:
            model = await asyncio.to_thread(self._load)
            pairs = [[query, c.get("content", "")] for c in candidates]
            scores = await asyncio.to_thread(lambda: model.compute_score(pairs, normalize=True))
        except Exception as e:  # noqa: BLE001
            log.warning("rerank.local.failed degraded_keep_rrf err=%s", e)
            return candidates[:top_n]
        if isinstance(scores, (int, float)):
            scores = [scores]
        # 按分降序取 top_n（compute_score 不保证返回顺序与输入一致时也安全）
        order = sorted(range(len(candidates)), key=lambda i: scores[i] if i < len(scores) else -1.0, reverse=True)
        out: List[dict] = []
        for idx in order[:top_n]:
            item = dict(candidates[idx])
            item["score"] = float(scores[idx]) if idx < len(scores) else 0.0
            item["source"] = "reranked"
            out.append(item)
        return out


def _order_by_results(candidates: List[dict], results: list[dict], top_n: int) -> List[dict]:
    """把 provider 返回的 [{index, relevance_score}] 映射回候选并按分排序。"""
    out: List[dict] = []
    for r in results:
        idx = r.get("index")
        if idx is None or idx >= len(candidates):
            continue
        item = dict(candidates[idx])
        item["score"] = float(r.get("relevance_score", 0.0))
        item["source"] = "reranked"
        out.append(item)
    return out[:top_n] if out else candidates[:top_n]


_reranker: Optional[Reranker] = None


def _make_local_reranker() -> Reranker:
    try:
        import FlagEmbedding  # noqa: F401
    except ImportError:
        log.warning(
            "reranker.local.unavailable FlagEmbedding 未安装 → NoOp "
            "（装可选 extra: pip install -e \".[rerank]\"）"
        )
        return NoOpReranker()
    return LocalFlagReranker(settings.rerank_model or "BAAI/bge-reranker-v2-m3")


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is not None:
        return _reranker

    provider = (settings.rerank_provider or "auto").lower()
    base = settings.rerank_base_url
    # API 类 provider：key 可复用 embedding（同账号同 key，省得重复填）
    api_key = settings.rerank_api_key or settings.embedding_api_key

    if provider == "local":
        _reranker = _make_local_reranker()
        if not isinstance(_reranker, NoOpReranker):
            log.info("reranker=local model=%s", settings.rerank_model or "BAAI/bge-reranker-v2-m3")
    elif provider == "dashscope" or (provider == "auto" and base and "aliyuncs" in base):
        if base and api_key:
            log.info("reranker=dashscope model=%s", settings.rerank_model)
            _reranker = DashScopeReranker(base, api_key, settings.rerank_model)
        else:
            _reranker = NoOpReranker()
    elif provider == "cross_encoder" or (provider == "auto" and base and api_key):
        log.info("reranker=cross_encoder model=%s", settings.rerank_model)
        _reranker = CrossEncoderReranker(base, api_key, settings.rerank_model)
    else:
        _reranker = NoOpReranker()
    return _reranker


def reset_reranker() -> None:
    """测试用：重置单例。"""
    global _reranker
    _reranker = None
