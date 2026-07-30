"""reranker 测试：provider 解析排序、降级、get_reranker 选择（plan_four §3 rerank 接入）。"""
from __future__ import annotations

import sys

import pytest

from app.services.retrieval import reranker
from app.services.retrieval.reranker import (
    CrossEncoderReranker,
    DashScopeReranker,
    NoOpReranker,
    get_reranker,
    reset_reranker,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_reranker()
    yield
    reset_reranker()


@pytest.mark.asyncio
async def test_noop_passthrough():
    cands = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
    assert await NoOpReranker().rerank("q", cands, 2) == cands[:2]


# ===== httpx 桩：拦截 reranker 内的 AsyncClient.post =====
class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Client:
    def __init__(self, payload):
        self._p = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return _Resp(self._p)


def _patch(monkeypatch, payload):
    monkeypatch.setattr(reranker.httpx, "AsyncClient", lambda **kw: _Client(payload))


@pytest.mark.asyncio
async def test_dashscope_orders_by_score(monkeypatch):
    # provider 返回 index 2 最高分 → 应排首位
    _patch(monkeypatch, {"output": {"results": [
        {"index": 2, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.4},
    ]}})
    cands = [{"content": "a", "doc_id": 1}, {"content": "b", "doc_id": 2}, {"content": "c", "doc_id": 3}]
    r = DashScopeReranker("https://x.aliyuncs.com/compatible-mode/v1", "k", "gte-rerank-v2")
    out = await r.rerank("q", cands, 3)
    assert [c["doc_id"] for c in out] == [3, 1]  # index2(doc3)→index0(doc1)
    assert out[0]["score"] == pytest.approx(0.9)
    assert out[0]["source"] == "reranked"


@pytest.mark.asyncio
async def test_dashscope_strips_compatible_mode_for_endpoint():
    # base_url 给兼容模式 URL 也应剥成 host + 原生 rerank 路径
    r = DashScopeReranker("https://x.aliyuncs.com/compatible-mode/v1", "k", "m")
    assert r.endpoint == "https://x.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


@pytest.mark.asyncio
async def test_dashscope_degrades_on_error(monkeypatch):
    class _ErrClient(_Client):
        async def post(self, url, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(reranker.httpx, "AsyncClient", lambda **kw: _ErrClient(None))
    cands = [{"content": "a"}, {"content": "b"}]
    out = await DashScopeReranker("https://x.aliyuncs.com", "k", "m").rerank("q", cands, 5)
    assert out == cands  # 失败 → 保留 RRF 原序


@pytest.mark.asyncio
async def test_cross_encoder_orders_by_score(monkeypatch):
    _patch(monkeypatch, {"results": [
        {"index": 1, "relevance_score": 0.8},
        {"index": 0, "relevance_score": 0.1},
    ]})
    cands = [{"content": "a"}, {"content": "b"}]
    out = await CrossEncoderReranker("https://api.cohere.com/v1", "k", "m").rerank("q", cands, 2)
    assert [c["content"] for c in out] == ["b", "a"]


def test_get_reranker_auto_dashscope_for_aliyun(monkeypatch):
    monkeypatch.setattr(reranker.settings, "rerank_provider", "auto")
    monkeypatch.setattr(reranker.settings, "rerank_base_url", "https://x.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(reranker.settings, "rerank_api_key", "")
    monkeypatch.setattr(reranker.settings, "embedding_api_key", "ek")  # 复用 embedding key
    monkeypatch.setattr(reranker.settings, "rerank_model", "gte-rerank-v2")
    assert isinstance(get_reranker(), DashScopeReranker)


def test_get_reranker_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(reranker.settings, "rerank_provider", "auto")
    monkeypatch.setattr(reranker.settings, "rerank_base_url", "")
    monkeypatch.setattr(reranker.settings, "rerank_api_key", "")
    monkeypatch.setattr(reranker.settings, "embedding_api_key", "")
    assert isinstance(get_reranker(), NoOpReranker)


def test_get_reranker_local_falls_back_when_flagembedding_missing(monkeypatch):
    # 强制 FlagEmbedding import 失败 → provider=local 应回退 NoOp，不抛
    monkeypatch.setattr(reranker.settings, "rerank_provider", "local")
    monkeypatch.setattr(reranker.settings, "rerank_model", "BAAI/bge-reranker-v2-m3")
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)
    assert isinstance(get_reranker(), NoOpReranker)
