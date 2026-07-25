"""Agentic RAG 测试（plan_three §2）。

策略：走启发式路径（settings.llm_api_key 默认空），monkeypatch orchestrator.retrieve
模拟召回，断言迭代收敛/上限/去重；selfcheck 走启发式。
"""
from __future__ import annotations

import pytest

from app.core.tenant import TenantContext
from app.schemas.chat import RetrievedChunk, RetrieveResponse
from app.services.generation import selfcheck as selfcheck_mod
from app.services.retrieval import agentic, orchestrator

Tenant = TenantContext(tenant_id="acme")


# ===== JSON 宽松解析 =====
def test_parse_json_loose_plain():
    assert agentic.parse_json_loose('{"sufficient": true, "score": 0.8}') == {"sufficient": True, "score": 0.8}


def test_parse_json_loose_codefenced():
    assert agentic.parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_loose_with_noise():
    assert agentic.parse_json_loose('结果如下：{"pass": false} 完毕') == {"pass": False}


def test_parse_json_loose_invalid_returns_none():
    assert agentic.parse_json_loose("not json at all") is None


# ===== 启发式 followup / 充分性 =====
def test_heuristic_followups_split():
    fu = agentic._heuristic_followups("苹果、香蕉、橙子")
    assert fu == ["苹果", "香蕉"]  # 取前 2


def test_heuristic_followups_nosplit_empty():
    assert agentic._heuristic_followups("单一问题") == []


def test_heuristic_assess_sufficient():
    chunks = [
        RetrievedChunk(chunk_id=1, doc_id=1, content="apple banana fruit", score=0.9),
        RetrievedChunk(chunk_id=2, doc_id=1, content="apple red", score=0.8),
        RetrievedChunk(chunk_id=3, doc_id=1, content="banana yellow", score=0.7),
    ]
    a = agentic._heuristic_assess("apple banana", chunks)
    assert a.sufficient is True
    assert a.followups == []
    assert a.score > 0.5


def test_heuristic_assess_insufficient_generates_followups():
    a = agentic._heuristic_assess("苹果、香蕉", [])
    assert a.sufficient is False
    assert len(a.followups) >= 1


# ===== 合并去重 =====
def test_merge_chunks_dedup_keep_best_score():
    a = RetrievedChunk(chunk_id=1, doc_id=1, content="x", score=0.5)
    b = RetrievedChunk(chunk_id=1, doc_id=1, content="x", score=0.9)  # 同 id 更高分
    c = RetrievedChunk(chunk_id=2, doc_id=1, content="y", score=0.3)
    merged = agentic.merge_chunks([a], [b, c])
    ids = sorted(m.chunk_id for m in merged)
    assert ids == [1, 2]
    win = next(m for m in merged if m.chunk_id == 1)
    assert win.score == 0.9  # 保留更高分


# ===== agentic_retrieve：收敛 =====
async def test_agentic_retrieve_converges_immediately(monkeypatch):
    async def fake(session, tenant, query, *, knowledge_base_id=None, top_k=None,
                   scene=None, history=None, permission=None):
        return RetrieveResponse(query=query, chunks=[
            RetrievedChunk(chunk_id=1, doc_id=1, content="apple banana fruit", score=0.9, source="fused"),
            RetrievedChunk(chunk_id=2, doc_id=1, content="apple red", score=0.8, source="fused"),
            RetrievedChunk(chunk_id=3, doc_id=1, content="banana yellow", score=0.7, source="fused"),
        ], degraded=[])

    monkeypatch.setattr(orchestrator, "retrieve", fake)
    res = await agentic.agentic_retrieve(None, Tenant, "apple banana", max_iterations=3)
    assert res.iterations == 1          # 首次即充分，未迭代
    assert res.followups_used == []
    assert len(res.chunks) == 3
    assert "agentic" in res.degraded


# ===== agentic_retrieve：迭代 + 上限 =====
async def test_agentic_retrieve_iterates_and_caps(monkeypatch):
    calls = [0]

    async def fake(session, tenant, query, *, knowledge_base_id=None, top_k=None,
                   scene=None, history=None, permission=None):
        calls[0] += 1
        # 每次返回新 chunk_id；内容与查询无关 → 永不充分，触发 followup 迭代
        return RetrieveResponse(
            query=query,
            chunks=[RetrievedChunk(chunk_id=calls[0], doc_id=1, content=f"无关内容{calls[0]}", score=0.5)],
            degraded=[],
        )

    monkeypatch.setattr(orchestrator, "retrieve", fake)
    # 查询含、→ 启发式产生 followup；max_iterations=2 → 最多 2 轮
    res = await agentic.agentic_retrieve(None, Tenant, "苹果、香蕉、橙子", max_iterations=2)
    assert res.iterations == 2                 # 触顶
    assert len(res.followups_used) == 2        # 苹果、香蕉
    assert len(res.chunks) >= 2                # 多轮去重合并后证据增长
    assert calls[0] >= 3                        # 首检 + 2 followup ≥ 3 次召回


async def test_agentic_retrieve_no_progress_converges(monkeypatch):
    """followup 未带来新证据（同 chunk_id）→ 提前收敛，不空转。"""
    async def fake(session, tenant, query, *, knowledge_base_id=None, top_k=None,
                   scene=None, history=None, permission=None):
        return RetrieveResponse(
            query=query,
            chunks=[RetrievedChunk(chunk_id=1, doc_id=1, content="无关", score=0.5)],
            degraded=[],
        )

    monkeypatch.setattr(orchestrator, "retrieve", fake)
    res = await agentic.agentic_retrieve(None, Tenant, "苹果、香蕉", max_iterations=4)
    assert res.iterations == 2  # 第一轮 followup 无新证据 → 收敛（不耗满 4 轮）


# ===== selfcheck 启发式 =====
async def test_selfcheck_pass_when_supported():
    chunks = [RetrievedChunk(chunk_id=1, doc_id=1, content="苹果是红色的水果，味道甜", score=0.9)]
    r = await selfcheck_mod.check_faithfulness("苹果是红色的水果", chunks)
    assert r.passed is True
    assert r.score > 0.5


async def test_selfcheck_fail_on_degradation_marker():
    r = await selfcheck_mod.check_faithfulness("生成失败，请检查 LLM 配置", [
        RetrievedChunk(chunk_id=1, doc_id=1, content="一些证据", score=0.9)
    ])
    assert r.passed is False


async def test_selfcheck_fail_on_no_coverage():
    r = await selfcheck_mod.check_faithfulness("量子纠缠隧穿效应", [
        RetrievedChunk(chunk_id=1, doc_id=1, content="今天天气晴朗", score=0.9)
    ])
    assert r.passed is False


async def test_selfcheck_neutral_without_evidence():
    r = await selfcheck_mod.check_faithfulness("某个回答", [])
    assert r.score == 0.5  # 无证据可校验，中性
