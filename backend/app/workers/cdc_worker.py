"""CDC Worker（设计书 §4.1，P2）：消费数据源变更事件 → 增量更新索引。

消费 Kafka `rag.cdc`（Debezium/Kafka Connect 写入）；每条事件解析后由
connectors/cdc.handle_cdc_event 处理（upsert 触发 ingest / delete 清理）。
Kafka 不可用则阻塞重连（CDC 为事件驱动，无 PG 兜底）。
"""
from __future__ import annotations

import asyncio
import signal

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.database import dispose_engine, session_scope
from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store
from app.services.ingestion.connectors import cdc as cdc_mod

log = get_logger(__name__)
_stop = asyncio.Event()


async def handle(raw: dict) -> None:
    try:
        event = cdc_mod.parse_event(raw)
        async with session_scope() as session:
            await cdc_mod.handle_cdc_event(session, event)
    except Exception as e:  # noqa: BLE001
        log.error("cdc.handle.failed raw=%s err=%s", raw, e)


async def main() -> None:
    setup_logging()
    log.info("cdc_worker.starting topic=%s group=%s", settings.kafka_cdc_topic, settings.kafka_cdc_group)
    object_storage.init_object_storage()
    await redis_store.init_redis()
    await opensearch_store.init_opensearch()
    await milvus_store.init_milvus()
    await kafka_bus.init_kafka()

    if not kafka_bus.is_available():
        log.warning("cdc_worker.kafka_unavailable — 阻塞重连（CDC 需 Kafka）")
        while not _stop.is_set():
            try:
                await asyncio.wait_for(_stop.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
        return

    try:
        async for msg in kafka_bus.consume(settings.kafka_cdc_topic, settings.kafka_cdc_group):
            if _stop.is_set():
                break
            await handle(msg)
    finally:
        await kafka_bus.close_kafka()
        await dispose_engine()
        log.info("cdc_worker.stopped")


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
