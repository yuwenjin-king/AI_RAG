"""异步数据处理 Worker（设计书 §4.1/§4.2）。

消费 Kafka `rag.ingest` 消息 {doc_id} → 解析→分块→embedding→双写→更新状态。
Kafka 不可用时，回退为轮询 PG 中 pending/failed 的文档（保证最小链路可跑通）。
"""
from __future__ import annotations

import asyncio
import signal

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.database import dispose_engine, session_scope
from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store
from app.services.ingest import process_document, process_pending

log = get_logger(__name__)
_stop = asyncio.Event()


async def handle(doc_id) -> None:
    try:
        async with session_scope() as session:
            await process_document(session, int(doc_id))
    except Exception as e:  # noqa: BLE001
        log.error("worker.handle.failed doc_id=%s err=%s", doc_id, e)


async def _kafka_mode() -> None:
    topic = settings.kafka_ingest_topic
    group = settings.kafka_consumer_group
    # 启动先扫一遍历史 pending
    async with session_scope() as s:
        n = await process_pending(s, 100)
    if n:
        log.info("worker.initial_sweep processed=%s", n)

    async for msg in kafka_bus.consume(topic, group):
        if _stop.is_set():
            break
        doc_id = msg.get("doc_id")
        if doc_id is not None:
            await handle(doc_id)


async def _poll_mode() -> None:
    log.warning("worker.poll_mode kafka_unavailable — 每 5s 扫描 pending/failed")
    while not _stop.is_set():
        try:
            async with session_scope() as s:
                n = await process_pending(s, 50)
            if n:
                log.info("worker.poll processed=%s", n)
        except Exception as e:  # noqa: BLE001
            log.error("worker.poll.error err=%s", e)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    setup_logging()
    log.info("worker.starting env=%s", settings.env)
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
        log.info("worker.stopped")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.add_signal_handler(signal.SIGINT, _stop.set)
        loop.add_signal_handler(signal.SIGTERM, _stop.set)
    except (NotImplementedError, RuntimeError):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: _stop.set)
    loop.run_until_complete(main())
