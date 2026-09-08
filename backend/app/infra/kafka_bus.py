"""Kafka（aiokafka）：异步数据处理管道 producer/consumer。

不可用时优雅降级：produce 返回 False，调用方回退到同步/本地处理。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_producer = None  # aiokafka.AIOKafkaProducer
_available = False


async def init_kafka() -> None:
    global _producer, _available
    try:
        from aiokafka import AIOKafkaProducer

        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            linger_ms=20,
        )
        await _producer.start()
        _available = True
        log.info("kafka.connected brokers=%s", settings.kafka_bootstrap_servers)
    except Exception as e:  # noqa: BLE001
        _available = False
        # 释放半初始化的 producer
        if _producer is not None:
            try:
                await _producer.stop()
            except Exception:  # noqa: BLE001
                pass
        _producer = None
        log.warning("kafka.unavailable degraded_async (err=%s)", e)


async def close_kafka() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


def is_available() -> bool:
    return _available


async def produce(topic: str, value: dict[str, Any], key: Optional[str] = None) -> bool:
    """发布消息。成功返回 True；不可用返回 False（调用方降级）。"""
    if not _available or _producer is None:
        log.debug("kafka.publish.skipped (unavailable) topic=%s", topic)
        return False
    try:
        await _producer.send_and_wait(topic, value, key=key)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("kafka.publish.failed degraded topic=%s err=%s", topic, e)
        return False


async def consume(
    topic: str,
    group_id: str,
    *,
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
    retry_backoff: float = 5.0,
) -> None:
    """消费并处理：on_message 成功返回后才 commit offset（at-least-once）。

    旧版 enable_auto_commit=True 是 at-most-once：auto-commit 定时器可能在
    处理完成前就提交 offset，worker 崩溃即丢在途消息（doc 卡中途状态）。
    现改为处理完一条 commit 一次；on_message 抛错则不提交，重启后重投——
    处理方须幂等（见 ingest.process_document 的 purge-before-reindex）。

    Kafka 不可用时阻塞重试（worker 主循环）。
    """
    from aiokafka import AIOKafkaConsumer

    while True:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=False,
        )
        try:
            await consumer.start()
            log.info("kafka.consumer.started topic=%s group=%s commit=after-process", topic, group_id)
            async for msg in consumer:
                try:
                    await on_message(msg.value)
                except Exception as e:  # noqa: BLE001
                    # 不 commit：当前消费位点在内存中仍前进，但重启后从上次
                    # commit 处重投（DB 状态权威 + 处理幂等 → 重投安全）
                    log.error("kafka.handle.failed topic=%s err=%s", topic, e)
                    continue
                await consumer.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("kafka.consumer.error retry_in=%ss err=%s", retry_backoff, e)
        finally:
            try:
                await consumer.stop()
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(retry_backoff)
