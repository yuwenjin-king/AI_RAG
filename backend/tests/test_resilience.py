"""韧性测试：熔断器 + 外部重试 + /readyz（plan_three §5）。"""
from __future__ import annotations

import pytest

from app.core import resilience
from app.core.resilience import CircuitBreaker, CircuitOpenError


# ===== 熔断器 =====
async def test_breaker_opens_and_short_circuits():
    calls = [0]

    async def fail():
        calls[0] += 1
        raise RuntimeError("boom")

    b = CircuitBreaker("t", failure_threshold=3, cooldown=10.0)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await b.call(fail)
    assert b.state == "open"
    # 开路 → 短路：抛 CircuitOpenError 且不再调用 fn
    with pytest.raises(CircuitOpenError):
        await b.call(fail)
    assert calls[0] == 3  # 第 4 次未真正调用


async def test_breaker_half_open_recovery():
    async def fail():
        raise RuntimeError("x")

    async def ok():
        return 7

    b = CircuitBreaker("t", failure_threshold=2, cooldown=0.0)  # cooldown=0 → 立即可半开
    with pytest.raises(RuntimeError):
        await b.call(fail)
    with pytest.raises(RuntimeError):
        await b.call(fail)
    assert b.state == "open"
    r = await b.call(ok)  # 半开试探成功 → 恢复闭合
    assert r == 7
    assert b.state == "closed"


async def test_breaker_success_resets_failures():
    async def fail():
        raise RuntimeError("x")

    async def ok():
        return 1

    b = CircuitBreaker("t", failure_threshold=3, cooldown=10.0)
    with pytest.raises(RuntimeError):
        await b.call(fail)
    with pytest.raises(RuntimeError):
        await b.call(fail)
    assert b.state == "closed"  # 仅 2 次，未达阈值
    await b.call(ok)  # 成功 → 失败计数重置
    with pytest.raises(RuntimeError):
        await b.call(fail)
    with pytest.raises(RuntimeError):
        await b.call(fail)
    assert b.state == "closed"  # 重新累计又只 2 次，仍未开


# ===== 外部调用重试 =====
async def test_retry_retries_transient_then_succeeds(monkeypatch):
    import httpx

    monkeypatch.setattr(resilience.settings, "retry_attempts", 3)
    monkeypatch.setattr(resilience.settings, "retry_multiplier", 0.01)
    monkeypatch.setattr(resilience.settings, "retry_max_wait", 0.05)
    calls = [0]

    @resilience.retry_external
    async def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise httpx.ConnectError("transient")
        return "ok"

    assert await flaky() == "ok"
    assert calls[0] == 3


async def test_retry_reraises_nontransient_immediately(monkeypatch):
    monkeypatch.setattr(resilience.settings, "retry_attempts", 3)
    calls = [0]

    @resilience.retry_external
    async def bad():
        calls[0] += 1
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        await bad()
    assert calls[0] == 1  # 非瞬时错误不重试


# ===== /readyz =====
async def test_readyz_ok_when_db_up(monkeypatch):
    from app.api.v1 import health
    from app.db import database

    async def _ok():
        return True

    monkeypatch.setattr(database, "ping", _ok)
    monkeypatch.setattr(health, "_shutting_down", False)
    resp = await health.readyz()
    assert resp.status_code == 200


async def test_readyz_503_when_shutting_down(monkeypatch):
    from app.api.v1 import health
    from app.db import database

    async def _ok():
        return True

    monkeypatch.setattr(database, "ping", _ok)
    monkeypatch.setattr(health, "_shutting_down", True)
    resp = await health.readyz()
    assert resp.status_code == 503


async def test_readyz_503_when_db_down(monkeypatch):
    from app.api.v1 import health
    from app.db import database

    async def _bad():
        return False

    monkeypatch.setattr(database, "ping", _bad)
    monkeypatch.setattr(health, "_shutting_down", False)
    resp = await health.readyz()
    assert resp.status_code == 503
