"""版面检测 / OCR Worker（设计书 §4.2.2 独立 GPU 池）。

消费 Kafka `rag.layout` 消息 {doc_id} → 版面检测 + 区域级 OCR → 清理旧索引 → 重新分块索引。
Kafka 不可用时轮询 status=layout_pending 的文档。vision_enabled=False 时直接退出（无需求）。
"""
from __future__ import annotations

import asyncio
import signal

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.database import dispose_engine, session_scope
from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store
from app.services.ingest import process_layout, process_layout_pending

log = get_logger(__name__)
_stop = asyncio.Event()


async def handle(doc_id) -> None:
    try:
        async with session_scope() as session:
            await process_layout(session, int(doc_id))
    except Exception as e:  # noqa: BLE001
        log.error("layout.handle.failed doc_id=%s err=%s", doc_id, e)


async def _kafka_mode() -> None:
    # 启动先扫一遍历史 layout_pending
    async with session_scope() as s:
        n = await process_layout_pending(s, 100)
    if n:
        log.info("layout.initial_sweep processed=%s", n)
    async for msg in kafka_bus.consume(settings.kafka_layout_topic, settings.kafka_layout_group):
        if _stop.is_set():
            break
        doc_id = msg.get("doc_id")
        if doc_id is not None:
            await handle(doc_id)


async def _poll_mode() -> None:
    log.warning("layout.poll_mode kafka_unavailable — 每 10s 扫描 layout_pending")
    while not _stop.is_set():
        try:
            async with session_scope() as s:
                n = await process_layout_pending(s, 50)
            if n:
                log.info("layout.poll processed=%s", n)
        except Exception as e:  # noqa: BLE001
            log.error("layout.poll.error err=%s", e)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    setup_logging()
    if not settings.vision_enabled:
        log.warning("layout_worker.vision_disabled — 退出（未启用视觉解析，扫描件走纯文本兜底）")
        return
    log.info(
        "layout_worker.starting detector=%s ocr=%s",
        settings.pdf_layout_detector, settings.ocr_engine,
    )
    object_storage.init_object_storage()
    await redis_store.init_redis()
    await opensearch_store.init_opensearch()
    await milvus_store.init_milvus()
    await kafka_bus.init_kafka()

    mode = _kafka_mode if kafka_bus.is_available() else _poll_mode
    task = asyncio.create_task(mode())
    try:
        await _stop.wait()
    finally:
        task.cancel()
        await kafka_bus.close_kafka()
        await dispose_engine()
        log.info("layout_worker.stopped")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.add_signal_handler(signal.SIGINT, _stop.set)
        loop.add_signal_handler(signal.SIGTERM, _stop.set)
    except (NotImplementedError, RuntimeError):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: _stop.set())
    loop.run_until_complete(main())
