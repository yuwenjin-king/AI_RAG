"""限流（设计书 §4.5 成本管控）：per-tenant 固定窗口计数。

Redis 可用 → 原子计数（集群一致）；不可用 → 本地滑动窗口兜底（单实例）。
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from app.core.metrics import RATE_LIMITED
from app.infra import redis_store

_local: Dict[str, List[float]] = defaultdict(list)


async def allow(
    tenant_id: str, *, endpoint: str = "chat", limit: int | None = None, window: int = 60
) -> bool:
    """是否放行。limit<=0 表示不限。"""
    from app.core.config import settings

    lim = settings.rate_limit_chat_per_min if limit is None else limit
    if lim <= 0:
        return True

    if redis_store.is_available():
        key = f"rl:{endpoint}:{tenant_id}"
        cnt = await redis_store.cache_incr(key, ttl=window)
        if cnt == 0:  # Redis 异常 → 本地兜底
            return _local_allow(tenant_id, endpoint, lim, window)
        if cnt > lim:
            RATE_LIMITED.labels(tenant=tenant_id, endpoint=endpoint).inc()
            return False
        return True
    return _local_allow(tenant_id, endpoint, lim, window)


def _local_allow(tenant_id: str, endpoint: str, lim: int, window: int) -> bool:
    now = time.monotonic()
    k = f"{endpoint}:{tenant_id}"
    arr = _local[k]
    cutoff = now - window
    while arr and arr[0] < cutoff:
        arr.pop(0)
    if len(arr) >= lim:
        RATE_LIMITED.labels(tenant=tenant_id, endpoint=endpoint).inc()
        return False
    arr.append(now)
    return True
