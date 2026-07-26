"""异步 SQLAlchemy 引擎与 Session（plan_three §5：连接池 config 化 + 慢查询 + ping）。"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
)


class Base(DeclarativeBase):
    pass


# 慢查询观测（设计书 §9 / plan_three §5）：超过阈值打 warning，便于定位瓶颈
if settings.db_slow_query_seconds > 0:

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        context._query_start = time.perf_counter()  # type: ignore[attr-defined]

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        start = getattr(context, "_query_start", None)
        if start is None:
            return
        elapsed = time.perf_counter() - start
        if elapsed >= settings.db_slow_query_seconds:
            log.warning("db.slow_query seconds=%.2f stmt=%s", elapsed, str(statement)[:200])


async def ping() -> bool:
    """轻量连通性探测（/readyz 用）。"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("db.ping.failed err=%s", e)
        return False


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供 DB Session。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """非请求上下文（worker）使用：自动提交/回滚。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    await engine.dispose()
