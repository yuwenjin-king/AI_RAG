"""FastAPI 应用入口（BFF + 服务层）。

lifespan 初始化全套 infra（各自独立降级），注册路由、CORS、全局异常处理。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.db.database import dispose_engine
from app.infra import (
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
    yield
    await kafka_bus.close_kafka()
    await redis_store.close_redis()
    await opensearch_store.close_opensearch()
    await milvus_store.close_milvus()
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

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
