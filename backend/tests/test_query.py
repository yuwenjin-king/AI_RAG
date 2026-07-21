import pytest

from app.services.retrieval import query as q


@pytest.mark.asyncio
async def test_plan_transparent_without_llm_key(monkeypatch):
    # 测试环境无 LLM_API_KEY → 改写/扩展透传，零外部调用
    monkeypatch.setattr(q.settings, "llm_api_key", "")
    qp = await q.plan("GLM 是什么", history=[{"role": "user", "content": "介绍下"}])
    assert qp.rewritten == "GLM 是什么"
    assert qp.expansions == ["GLM 是什么"]
    assert qp.use_structured is False


@pytest.mark.asyncio
async def test_rewrite_disabled_passthrough(monkeypatch):
    monkeypatch.setattr(q.settings, "llm_api_key", "fake-key")
    monkeypatch.setattr(q.settings, "query_rewrite_enabled", False)
    out = await q.rewrite("它怎么样", history=[{"role": "user", "content": "x"}])
    assert out == "它怎么样"


@pytest.mark.asyncio
async def test_expand_capped(monkeypatch):
    # 即便 LLM 不可达，expand 也应优雅降级为仅原查询（complete 抛异常被捕获）
    monkeypatch.setattr(q.settings, "llm_api_key", "fake-key")
    out = await q.expand("some query")
    assert isinstance(out, list) and out[0] == "some query"
    assert len(out) <= 3  # 原查询 + 最多 2 扩展
