"""韧性：熔断器 + 外部调用重试（plan_three §5）。

熔断器：外部依赖（LLM/embedding API）连续失败达阈值 → 开路（快速失败，直接降级），
冷却后半开试探一次，成功则恢复。避免依赖宕机时每请求都挂起/超时。
重试：对瞬时错误（连接/超时）指数退避，重试耗尽才计入熔断失败。

 breaker.call(retry_external(fn), ...) —— 重试在内、熔断在外：瞬时抖动被重试吸收，
 只有持续失败才开路。
"""
from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable, Dict

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class CircuitOpenError(Exception):
    """熔断器开路时抛出，调用方应据此降级（不重试）。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"circuit open: {name}")


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self, name: str, *,
        failure_threshold: int = 5, cooldown: float = 30.0, success_threshold: int = 1,
    ):
        self.name = name
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown
        self._success_threshold = success_threshold
        self._state = self.CLOSED
        self._failures = 0
        self._half_successes = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def check(self) -> None:
        """入口检查：开路且未过冷却 → 抛 CircuitOpenError；过冷却 → 转半开。"""
        async with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._opened_at < self._cooldown:
                    raise CircuitOpenError(self.name)
                self._state = self.HALF_OPEN
                self._half_successes = 0

    async def record_success(self) -> None:
        async with self._lock:
            if self._state == self.HALF_OPEN:
                self._half_successes += 1
                if self._half_successes >= self._success_threshold:
                    self._state = self.CLOSED
                    self._failures = 0
                    log.info("circuit.recovered name=%s", self.name)
            else:
                self._failures = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            was = self._state
            if self._state == self.HALF_OPEN or self._failures >= self._failure_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                if was != self.OPEN:
                    log.warning("circuit.opened name=%s failures=%s", self.name, self._failures)

    async def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """熔断包装：开路快速失败；成功/失败记录状态。fn 应已用 retry_external 包过。"""
        await self.check()
        try:
            result = await fn(*args, **kwargs)
        except CircuitOpenError:
            raise
        except Exception:
            await self.record_failure()
            raise
        await self.record_success()
        return result


_breakers: Dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str, *,
    failure_threshold: int | None = None, cooldown: float | None = None,
    success_threshold: int | None = None,
) -> CircuitBreaker:
    """单例熔断器（按 name 复用）。阈值取参数或 settings 默认。"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name,
            failure_threshold=failure_threshold or settings.circuit_failure_threshold,
            cooldown=cooldown if cooldown is not None else settings.circuit_cooldown,
            success_threshold=success_threshold or settings.circuit_success_threshold,
        )
    return _breakers[name]


def reset_breakers() -> None:
    """测试用：清空所有熔断器。"""
    _breakers.clear()


def retry_external(fn: Callable) -> Callable:
    """装饰器：对外部调用做指数退避重试（仅瞬时错误：连接/超时）。

    每次 CALL 时读取 settings（测试可 monkeypatch）。重试耗尽后 reraise 原异常。
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        import httpx
        from tenacity import (
            AsyncRetrying,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.retry_attempts),
            wait=wait_exponential(multiplier=settings.retry_multiplier, max=settings.retry_max_wait),
            retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout)),
            reraise=True,
        ):
            with attempt:
                return await fn(*args, **kwargs)

    return wrapper
