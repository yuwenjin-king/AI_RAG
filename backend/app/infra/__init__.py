"""infra 客户端聚合 + CLI 共用初始化。

web 进程经 `app.main.lifespan` 初始化；CLI 进程（eval / seed --index / dr）不经 lifespan，
须显式调用 `init_stores()`，否则各模块 `_available` 标志全 False → 向量/关键词检索退化为
本地兜底、索引写入被跳过（2026-07 §3 真实跑暴露：eval CLI 一直在用本地 BM25 而非真实 infra）。
"""
from __future__ import annotations


async def init_stores() -> None:
    """初始化全套可选 infra（各自独立降级，单个失败不影响其余）。

    顺序与 main.py lifespan 一致；每模块自检 settings.*_enabled 开关。
    """
    from app.infra import kafka_bus, milvus_store, object_storage, opensearch_store, redis_store

    object_storage.init_object_storage()
    await redis_store.init_redis()
    await opensearch_store.init_opensearch()
    await milvus_store.init_milvus()
    await kafka_bus.init_kafka()


async def close_stores() -> None:
    """对称关闭 infra 连接（顺序与 init 相反方向收尾）。"""
    from app.infra import kafka_bus, milvus_store, opensearch_store, redis_store

    await kafka_bus.close_kafka()
    await redis_store.close_redis()
    await opensearch_store.close_opensearch()
    await milvus_store.close_milvus()
