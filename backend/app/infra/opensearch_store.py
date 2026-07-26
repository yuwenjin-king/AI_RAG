"""OpenSearch：每租户 index，BM25 倒排 + 结构化过滤。

不可用时优雅降级（search_bm25 返回空），主链路回退到本地 BM25 兜底（见 retrieval/keyword.py）。
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext

log = get_logger(__name__)

_client = None  # opensearchpy.AsyncOpenSearch
_available = False
_ensured: set[str] = set()

# index settings + mapping（运行时建索引与 DR 重建共用，避免漂移）
_INDEX_BODY: dict[str, Any] = {
    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "properties": {
            "chunk_id": {"type": "long"},
            "doc_id": {"type": "long"},
            "tenant_id": {"type": "keyword"},
            "knowledge_base_id": {"type": "long"},
            "title": {"type": "text"},
            "content": {"type": "text"},
            "page_no": {"type": "integer"},
            "bbox": {"type": "object", "enabled": False},
            "tags": {"type": "keyword"},
        }
    },
}


async def init_opensearch() -> None:
    global _client, _available
    if not settings.opensearch_enabled:
        return
    try:
        from opensearchpy import AsyncOpenSearch

        kw: dict[str, Any] = {"hosts": [settings.opensearch_url]}
        if settings.opensearch_user and settings.opensearch_password:
            kw["http_auth"] = (settings.opensearch_user, settings.opensearch_password)
        _client = AsyncOpenSearch(**kw, timeout=30, max_retries=3, retry_on_timeout=True)
        if not await _client.ping():
            raise RuntimeError("ping failed")
        _available = True
        log.info("opensearch.connected url=%s", settings.opensearch_url)
    except Exception as e:  # noqa: BLE001
        _available = False
        log.warning("opensearch.unavailable degraded_keyword (err=%s)", e)


async def close_opensearch() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def is_available() -> bool:
    return _available


async def ensure_index_by_name(idx: str) -> str:
    """确保指定 index 存在（mapping 来自 _INDEX_BODY），返回 index 名。DR 重建复用。"""
    if not _available or _client is None:
        return idx
    if idx in _ensured:
        return idx
    try:
        exists = await _client.indices.exists(index=idx)
        if not exists:
            await _client.indices.create(index=idx, body=_INDEX_BODY)
            log.info("opensearch.index_created index=%s", idx)
        _ensured.add(idx)
    except Exception as e:  # noqa: BLE001
        log.warning("opensearch.ensure_index.failed index=%s err=%s", idx, e)
    return idx


async def ensure_index(tenant: TenantContext) -> str:
    """确保租户 index 存在，返回 index 名。"""
    return await ensure_index_by_name(tenant.index)


def _index_doc(chunk_id: int, doc_id: int, tenant_id: str, title: str, content: str,
               page_no: Optional[int], bbox: Optional[list], kb_id: Optional[int],
               tags: Optional[list]) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "knowledge_base_id": kb_id,
        "title": title,
        "content": content,
        "page_no": page_no,
        "bbox": bbox,
        "tags": tags or [],
    }


async def index_chunks(
    tenant: TenantContext, docs: list[dict[str, Any]], batch_size: int = 200
) -> int:
    if not _available or _client is None or not docs:
        return 0
    idx = await ensure_index(tenant)
    return await bulk_index(idx, docs, batch_size=batch_size)


async def bulk_index(idx: str, docs: list[dict[str, Any]], batch_size: int = 200) -> int:
    """按 index 名批量写入（index_chunks 的底层；DR 恢复直接用）。"""
    if not _available or _client is None or not docs:
        return 0
    count = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        body: list[Any] = []
        for d in batch:
            body.append({"index": {"_index": idx, "_id": str(d["chunk_id"])}})
            body.append(d)
        try:
            await _client.bulk(body=body)
            count += len(batch)
        except Exception as e:  # noqa: BLE001
            log.warning("opensearch.bulk.failed index=%s err=%s", idx, e)
    return count


async def search_bm25(
    tenant: TenantContext,
    query: str,
    topk: int,
    *,
    knowledge_base_id: Optional[int] = None,
    permission: Optional["PermissionFilter"] = None,
) -> list[dict[str, Any]]:
    """BM25 召回，返回 [{chunk_id, doc_id, score, content, title, page_no, bbox}]。

    权限前置过滤：注入 doc_id / knowledge_base_id terms 过滤。
    """
    if not _available or _client is None or not query.strip():
        return []
    idx = await ensure_index(tenant)
    filt: list[dict[str, Any]] = [{"term": {"tenant_id": tenant.tenant_id}}]
    if knowledge_base_id is not None:
        filt.append({"term": {"knowledge_base_id": knowledge_base_id}})
    if permission is not None:
        if permission.knowledge_base_ids is not None:
            filt.append({"terms": {"knowledge_base_id": list(permission.knowledge_base_ids)}})
        if permission.doc_ids is not None:
            filt.append({"terms": {"doc_id": list(permission.doc_ids)}})
    body = {
        "size": topk,
        "query": {
            "bool": {
                "must": [{"multi_match": {"query": query, "fields": ["content^2", "title"]}}],
                "filter": filt,
            }
        },
        "_source": ["chunk_id", "doc_id", "content", "title", "page_no", "bbox"],
    }
    try:
        resp = await _client.search(index=idx, body=body)
        hits = resp.get("hits", {}).get("hits", [])
        out = []
        for h in hits:
            s = h.get("_source", {})
            out.append(
                {
                    "chunk_id": s.get("chunk_id"),
                    "doc_id": s.get("doc_id"),
                    "score": float(h.get("_score", 0.0)),
                    "content": s.get("content", ""),
                    "title": s.get("title", ""),
                    "page_no": s.get("page_no"),
                    "bbox": s.get("bbox"),
                    "source": "bm25",
                }
            )
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("opensearch.search.failed index=%s err=%s", idx, e)
        return []


async def delete_by_doc(tenant: TenantContext, doc_id: int) -> None:
    if not _available or _client is None:
        return
    idx = tenant.index
    try:
        await _client.delete_by_query(index=idx, body={"query": {"term": {"doc_id": doc_id}}})
    except Exception as e:  # noqa: BLE001
        log.warning("opensearch.delete_by_doc.failed index=%s doc=%s err=%s", idx, doc_id, e)


# ===== DR 备份/恢复（plan_three §6）：批量导出/导入 =====
async def list_rag_indexes() -> list[str]:
    """所有 rag-chunks-* index（每租户一个）。不可用→[]。"""
    if not _available or _client is None:
        return []
    try:
        mapping = await _client.indices.get("rag-chunks-*")
        return sorted(mapping.keys())
    except Exception as e:  # noqa: BLE001
        log.warning("opensearch.list_indexes.failed err=%s", e)
        return []


async def export_index(idx: str, *, size: int = 1000) -> list[dict[str, Any]]:
    """scroll 导出 index 全量 _source。不可用/失败→[]。"""
    if not _available or _client is None:
        return []
    out: list[dict[str, Any]] = []
    scroll_id: str | None = None
    try:
        resp = await _client.search(
            index=idx,
            body={"size": size, "query": {"match_all": {}}, "_source": True},
            scroll="5m",
        )
        scroll_id = resp.get("_scroll_id")
        hits = resp.get("hits", {}).get("hits", [])
        while hits:
            for h in hits:
                src = h.get("_source")
                if src:
                    out.append(src)
            resp = await _client.scroll(scroll_id=scroll_id, scroll="5m")
            scroll_id = resp.get("_scroll_id", scroll_id)
            hits = resp.get("hits", {}).get("hits", [])
    except Exception as e:  # noqa: BLE001
        log.warning("opensearch.export.failed index=%s err=%s", idx, e)
    finally:
        if scroll_id and _available and _client is not None:
            try:
                await _client.clear_scroll(scroll_id=scroll_id)
            except Exception:  # noqa: BLE001
                pass
    return out
