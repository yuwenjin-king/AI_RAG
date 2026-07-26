"""健康检查 + 就绪探针 + 平台状态（plan_three §5：/healthz 与 /readyz 分离）。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import database
from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store

router = APIRouter()

# 优雅关停标志：lifespan 关停时置 True，让 /readyz 返回 503 以排流
_shutting_down = False


def mark_shutting_down() -> None:
    global _shutting_down
    _shutting_down = True


@router.get("/healthz")
async def healthz():
    """存活探针：进程能响应即 ok（不依赖 infra）。"""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """就绪探针：DB 连通 + 未在关停 → 200；否则 503（k8s/反代据此停止导流）。

    其余 infra（Milvus/OpenSearch/Kafka/MinIO）宕机时应用可降级运行，故不作为就绪硬门槛。
    """
    db_ok = await database.ping()
    ready = db_ok and not _shutting_down
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "db": db_ok, "shutting_down": _shutting_down},
    )


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
