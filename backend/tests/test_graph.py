"""GraphRAG 测试：内存图存储 / 启发式抽取 / 图召回。"""
import pytest

from app.core.config import settings as cfg
from app.core.tenant import TenantContext
from app.infra import graph_store
from app.services.knowledge import graph as graph_mod
from app.services.retrieval import graph as graph_recall_mod


def test_inmemory_store_upsert_query_delete():
    s = graph_store.InMemoryGraphStore()
    s.upsert_chunk_entities("A", doc_id=1, chunk_id=10, entities=["GLM", "RAG"])
    s.upsert_chunk_entities("A", doc_id=2, chunk_id=20, entities=["GLM"])
    neighbors = s.query_neighbors("A", ["glm", "rag"], topk=10)
    ids = {n["chunk_id"] for n in neighbors}
    assert ids == {10, 20}  # 共享 GLM 实体
    # 共享两个实体的 chunk（doc1）排更前、得分更高
    top = neighbors[0]
    assert top["chunk_id"] == 10 and top["score"] == 2

    s.delete_doc("A", doc_id=1)
    assert all(n["doc_id"] != 1 for n in s.query_neighbors("A", ["glm", "rag"], 10))


def test_extract_heuristic(monkeypatch):
    monkeypatch.setattr(cfg, "llm_api_key", "")
    monkeypatch.setattr(cfg, "graph_extraction", "heuristic")
    ents, rels = graph_mod._extract_heuristic("GLM 与 RAG 平台；知识图谱 Knowledge Graph。")
    lower = [e.lower() for e in ents]
    assert "glm" in lower
    assert "rag" in lower
    # 中文实体
    assert any("知识" in e or "图谱" in e for e in ents)
    assert rels == []


@pytest.mark.asyncio
async def test_graph_recall_end_to_end(monkeypatch):
    monkeypatch.setattr(cfg, "graph_enabled", True)
    monkeypatch.setattr(cfg, "neo4j_url", "")
    monkeypatch.setattr(cfg, "llm_api_key", "")
    monkeypatch.setattr(cfg, "graph_extraction", "heuristic")
    graph_store.init_graph()  # InMemory
    store = graph_store.get_store()
    assert store is not None
    store.upsert_chunk_entities("A", doc_id=1, chunk_id=10, entities=["glm"])

    hits, deg = await graph_recall_mod.graph_recall(TenantContext("A"), "GLM", 10)
    assert hits and hits[0]["chunk_id"] == 10
    assert hits[0]["source"] == "graph"

    # 权限过滤：禁止 doc 1 → 不返回
    from app.governance.authz import PermissionFilter

    hits2, _ = await graph_recall_mod.graph_recall(
        TenantContext("A"), "GLM", 10, permission=PermissionFilter(denied_doc_ids={1})
    )
    assert hits2 == []


@pytest.mark.asyncio
async def test_graph_recall_disabled(monkeypatch):
    monkeypatch.setattr(cfg, "graph_enabled", False)
    hits, deg = await graph_recall_mod.graph_recall(TenantContext("A"), "x", 10)
    assert hits == [] and deg == []
