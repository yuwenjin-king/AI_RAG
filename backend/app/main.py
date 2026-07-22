"""FastAPI 应用入口（BFF + 服务层）。

lifespan 初始化全套 infra（各自独立降级），注册路由、CORS、全局异常处理。
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.db.database import dispose_engine
from app.infra import (
    graph_store,
    kafka_bus,
    milvus_store,
    object_storage,
    opensearch_store,
    redis_store,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # 各 infra 独立初始化，单个不可用不影响其余（优雅降级）
    object_storage.init_object_storage()
    await redis_store.init_redis()
    await opensearch_store.init_opensearch()
    await milvus_store.init_milvus()
    await kafka_bus.init_kafka()
    graph_store.init_graph()
    yield
    await kafka_bus.close_kafka()
    await redis_store.close_redis()
    await opensearch_store.close_opensearch()
    await milvus_store.close_milvus()
    await graph_store.close_graph()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Enterprise RAG Platform",
        version="0.1.0",
        description="多租户 RAG 检索平台（FastAPI BFF + 服务层）",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            resp = JSONResponse(status_code=500, content={"code": "internal_error"})
        try:
            elapsed = time.perf_counter() - start
            path = request.url.path
            # 归一化带 id 的路径，避免指标爆炸
            for seg in path.split("/"):
                if seg.isdigit():
                    path = path.replace(seg, ":id")
            method = request.method
            status = str(getattr(resp, "status_code", 500))
            HTTP_REQUESTS.labels(method=method, path=path, status=status).inc()
            HTTP_LATENCY.labels(method=method, path=path).observe(elapsed)
        except Exception:  # noqa: BLE001
            pass
        return resp

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
