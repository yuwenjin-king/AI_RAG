"""Redis 客户端：查询结果缓存、热点 embedding 缓存、会话。

不可用时优雅降级（返回 None），不阻塞主链路。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client = None  # redis.asyncio.Redis
_available = False


async def init_redis() -> None:
    global _client, _available
    if not settings.redis_enabled:
        return
    try:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _client.ping()
        _available = True
        log.info("redis.connected url=%s", settings.redis_url)
    except Exception as e:  # noqa: BLE001
        _available = False
        log.warning("redis.unavailable degraded_caching (err=%s)", e)


async def close_redis() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def is_available() -> bool:
    return _available


async def cache_get(key: str) -> Optional[Any]:
    if not _available or _client is None:
        return None
    try:
        raw = await _client.get(key)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    if not _available or _client is None:
        return
    try:
        await _client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
    except Exception:  # noqa: BLE001
        pass
