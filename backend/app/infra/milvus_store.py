"""Milvus：每租户/共享 collection，HNSW + COSINE 向量召回。

不可用时优雅降级（search 返回空），主链路回退到仅 BM25（见 retrieval/orchestrator.py）。
pymilvus 的 MilvusClient 是同步 API，这里用 asyncio.to_thread 包装为异步。
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext

log = get_logger(__name__)

_client = None  # pymilvus.MilvusClient
_available = False
_ensured: set[str] = set()


def _connect_sync() -> bool:
    global _client, _available
    try:
        from pymilvus import MilvusClient, utility  # noqa: F401
        from pymilvus import connections  # noqa: F401

        uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
        _client = MilvusClient(uri=uri, timeout=15)
        # ping
        _client.list_collections()
        _available = True
        log.info("milvus.connected uri=%s dim=%s", uri, settings.embedding_dim)
        return True
    except Exception as e:  # noqa: BLE001
        _client = None
        _available = False
        log.warning("milvus.unavailable degraded_vector (err=%s)", e)
        return False


async def init_milvus() -> None:
    if not settings.milvus_enabled:
        return
    await asyncio.to_thread(_connect_sync)


async def close_milvus() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None


def is_available() -> bool:
    return _available


def _ensure_collection_sync(tenant: TenantContext) -> str:
    from pymilvus import DataType, MilvusClient

    name = tenant.collection
    if name in _ensured:
        return name
    client: MilvusClient = _client  # type: ignore[assignment]
    if not client.has_collection(name):
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("vector_id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=settings.embedding_dim)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
        schema.add_field("doc_id", DataType.INT64)
        schema.add_field("chunk_id", DataType.INT64)
        schema.add_field("kb_id", DataType.INT64)
        schema.add_field("content", DataType.VARCHAR, max_length=8192)
        client.create_collection(collection_name=name, schema=schema)
        log.info("milvus.collection_created name=%s", name)
    # 确保索引
    client.create_index(
        collection_name=name,
        field_name="embedding",
        index_type="HNSW",
        metric_type="COSINE",
        index_params={"M": 16, "efConstruction": 256},
    )
    try:
        client.load_collection(name)
    except Exception:  # noqa: BLE001
        pass
    _ensured.add(name)
    return name


async def ensure_collection(tenant: TenantContext) -> str:
    if not _available or _client is None:
        return tenant.collection
    return await asyncio.to_thread(_ensure_collection_sync, tenant)


async def upsert(tenant: TenantContext, records: list[dict[str, Any]]) -> int:
    """records: [{vector_id, embedding, tenant_id, doc_id, chunk_id, kb_id, content}]"""
    if not _available or _client is None or not records:
        return 0
    name = await ensure_collection(tenant)

    def _do():
        client = _client
        client.upsert(collection_name=name, data=records)
        return len(records)

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:  # noqa: BLE001
        log.warning("milvus.upsert.failed name=%s err=%s", name, e)
        return 0


async def search(
    tenant: TenantContext,
    query_vector: list[float],
    topk: int,
    *,
    knowledge_base_id: Optional[int] = None,
    kb_ids: Optional[list[int]] = None,
    doc_ids: Optional[list[int]] = None,
) -> list[dict[str, Any]]:
    if not _available or _client is None or not query_vector:
        return []
    name = await ensure_collection(tenant)
    esc = tenant.tenant_id.replace('"', "")
    filt = f'tenant_id == "{esc}"'
    if knowledge_base_id is not None:
        filt += f" and kb_id == {int(knowledge_base_id)}"
    if kb_ids:
        filt += " and kb_id in [" + ",".join(str(int(k)) for k in kb_ids) + "]"
    if doc_ids:
        filt += " and doc_id in [" + ",".join(str(int(d)) for d in doc_ids) + "]"

    def _do():
        client = _client
        return client.search(
            collection_name=name,
            data=[query_vector],
            anns_field="embedding",
            limit=topk,
            filter=filt,
            output_fields=["chunk_id", "doc_id", "kb_id", "content", "tenant_id"],
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )

    try:
        res = await asyncio.to_thread(_do)
        out: list[dict[str, Any]] = []
        if res:
            for hit in res[0]:
                entity = hit.get("entity", {})
                out.append(
                    {
                        "chunk_id": entity.get("chunk_id"),
                        "doc_id": entity.get("doc_id"),
                        "kb_id": entity.get("kb_id"),
                        "content": entity.get("content", ""),
                        "score": float(hit.get("distance", 0.0)),
                        "source": "vector",
                    }
                )
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("milvus.search.failed name=%s err=%s", name, e)
        return []


async def delete_by_doc(tenant: TenantContext, doc_id: int) -> None:
    if not _available or _client is None:
        return
    name = tenant.collection

    def _do():
        _client.delete(collection_name=name, filter=f"doc_id == {int(doc_id)}")

    try:
        await asyncio.to_thread(_do)
    except Exception as e:  # noqa: BLE001
        log.warning("milvus.delete_by_doc.failed name=%s doc=%s err=%s", name, doc_id, e)
