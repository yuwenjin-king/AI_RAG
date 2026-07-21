"""健康检查 + 平台状态（各 infra 可用性）。"""
from __future__ import annotations

from fastapi import APIRouter

from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/status")
async def status():
    """各 infra 在线状态，便于排障与降级观察。"""
    return {
        "object_storage": object_storage.is_available(),
        "redis": redis_store.is_available(),
        "opensearch": opensearch_store.is_available(),
        "milvus": milvus_store.is_available(),
        "kafka": kafka_bus.is_available(),
    }
