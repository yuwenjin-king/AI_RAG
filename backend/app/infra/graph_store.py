"""图存储（设计书 §4.3 GraphRAG）：实体—chunk 关联与邻居检索。

- InMemoryGraphStore：开发/测试兜底（neo4j 不可用或未配置时）
- Neo4jGraphStore：生产图库（neo4j 驱动懒加载 + 降级）
两者实现同一 GraphStore 接口；按可用性自动选择。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class GraphStore(ABC):
    name: str = "base"

    @abstractmethod
    def upsert_chunk_entities(
        self, tenant_id: str, doc_id: int, chunk_id: int, entities: Iterable[str]
    ) -> None: ...

    @abstractmethod
    def query_neighbors(
        self, tenant_id: str, entities: Iterable[str], topk: int
    ) -> list[dict]:
        """返回 [{chunk_id, doc_id, score}]，按共享实体数排序。"""
        ...

    @abstractmethod
    def delete_doc(self, tenant_id: str, doc_id: int) -> None: ...


class InMemoryGraphStore(GraphStore):
    """entity -> {(tenant, chunk_id, doc_id)}；逆向 chunk 查询。开发/测试用。"""

    name = "memory"

    def __init__(self) -> None:
        # entity -> set((chunk_id, doc_id))  （按 tenant 隔离分桶）
        self._index: dict[str, dict[str, set[tuple[int, int]]]] = {}

    def _bucket(self, tenant_id: str) -> dict[str, set[tuple[int, int]]]:
        return self._index.setdefault(tenant_id, {})

    def upsert_chunk_entities(
        self, tenant_id: str, doc_id: int, chunk_id: int, entities: Iterable[str]
    ) -> None:
        bucket = self._bucket(tenant_id)
        for ent in entities:
            ent = (ent or "").strip().lower()
            if not ent:
                continue
            bucket.setdefault(ent, set()).add((chunk_id, doc_id))

    def query_neighbors(
        self, tenant_id: str, entities: Iterable[str], topk: int
    ) -> list[dict]:
        bucket = self._bucket(tenant_id)
        scores: dict[int, dict] = {}  # chunk_id -> {doc_id, score}
        for ent in entities:
            ent = (ent or "").strip().lower()
            for chunk_id, doc_id in bucket.get(ent, set()):
                slot = scores.setdefault(chunk_id, {"chunk_id": chunk_id, "doc_id": doc_id, "score": 0})
                slot["score"] += 1
        ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:topk]
        return ranked

    def delete_doc(self, tenant_id: str, doc_id: int) -> None:
        bucket = self._bucket(tenant_id)
        for ent in list(bucket.keys()):
            bucket[ent] = {(c, d) for (c, d) in bucket[ent] if d != doc_id}
            if not bucket[ent]:
                del bucket[ent]


class Neo4jGraphStore(GraphStore):
    """Neo4j 图库：(Entity)-[:MENTIONED_BY]->(Chunk)。neo4j 驱动懒加载。"""

    name = "neo4j"

    def __init__(self, url: str, user: str, password: str):
        self.url, self.user, self.password = url, user, password
        self._driver = None

    def _conn(self):
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(self.url, auth=(self.user, self.password))
            self._driver.verify_connectivity()
        return self._driver

    def upsert_chunk_entities(
        self, tenant_id: str, doc_id: int, chunk_id: int, entities: Iterable[str]
    ) -> None:
        ents = [e.strip().lower() for e in entities if e and e.strip()]
        if not ents:
            return
        cypher = (
            "UNWIND $ents AS name "
            "MERGE (e:Entity {name: name, tenant: $tenant}) "
            "MERGE (c:Chunk {id: $chunk_id}) SET c.doc_id = $doc_id, c.tenant = $tenant "
            "MERGE (e)-[:MENTIONED_BY]->(c)"
        )
        with self._conn().session() as s:
            s.run(cypher, tenant=tenant_id, doc_id=doc_id, chunk_id=chunk_id, ents=ents)

    def query_neighbors(
        self, tenant_id: str, entities: Iterable[str], topk: int
    ) -> list[dict]:
        ents = [e.strip().lower() for e in entities if e and e.strip()]
        if not ents:
            return []
        cypher = (
            "MATCH (e:Entity {tenant: $tenant})-[:MENTIONED_BY]->(c:Chunk) "
            "WHERE e.name IN $ents "
            "RETURN c.id AS chunk_id, c.doc_id AS doc_id, count(e) AS score "
            "ORDER BY score DESC LIMIT $topk"
        )
        with self._conn().session() as s:
            rows = s.run(cypher, tenant=tenant_id, ents=ents, topk=topk).data()
        return [
            {"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "score": float(r["score"])}
            for r in rows
        ]

    def delete_doc(self, tenant_id: str, doc_id: int) -> None:
        cypher = "MATCH (c:Chunk {tenant: $tenant, doc_id: $doc_id}) DETACH DELETE c"
        with self._conn().session() as s:
            s.run(cypher, tenant=tenant_id, doc_id=doc_id)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


_store: Optional[GraphStore] = None
_available = False


def init_graph() -> None:
    global _store, _available
    if not settings.graph_enabled:
        return
    if settings.neo4j_url:
        try:
            _store = Neo4jGraphStore(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password)
            _store._conn()  # type: ignore[attr-defined]  # 触发连接校验
            _available = True
            log.info("graph.store=neo4j url=%s", settings.neo4j_url)
        except Exception as e:  # noqa: BLE001
            log.warning("graph.neo4j.unavailable fallback=memory err=%s", e)
            _store = InMemoryGraphStore()
            _available = True  # 内存兜底仍可用
    else:
        _store = InMemoryGraphStore()
        _available = True
        log.info("graph.store=memory (未配置 neo4j_url，开发/兜底)")


async def close_graph() -> None:
    global _store
    if isinstance(_store, Neo4jGraphStore):
        _store.close()
    _store = None


def is_available() -> bool:
    return _available


def get_store() -> Optional[GraphStore]:
    return _store
