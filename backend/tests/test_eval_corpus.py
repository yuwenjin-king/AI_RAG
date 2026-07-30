"""评估语料离线回归门禁（plan_four §2）。

seed 确定性语料 → run_eval（BM25 本地兜底 + mock generate）→ 断言检索/引用/溯源/生成
指标高于基线。证明 chunking→BM25→指标→bbox→faithfulness 全链路无回归。

诚实边界：本机无 Milvus/OpenSearch/LLM，故仅证 BM25 关键词路 + 指标管线；
真实混合检索效果（向量+BM25+rerank+真实 faithfulness）由 plan_four §3 在真实环境跑。
"""
from __future__ import annotations

import pytest

from app.core import config
from app.core.tenant import TenantContext
from app.eval import corpus as C
from app.eval.runner import run_eval
from app.eval.seed import index_eval_corpus, seed_eval_corpus


@pytest.fixture(autouse=True)
def _deterministic_retrieval(monkeypatch):
    # 关闭 LLM 查询改写/扩展 → 单子查询确定性 BM25（本机无 LLM/Milvus/OpenSearch）
    monkeypatch.setattr(config.settings, "query_rewrite_enabled", False)
    monkeypatch.setattr(config.settings, "query_expansion_enabled", False)


@pytest.mark.asyncio
async def test_seed_corpus_counts_and_idempotent(sqlite_session):
    res = await seed_eval_corpus(sqlite_session, TenantContext("default"))
    assert res["n_docs"] == len(C.CORPUS_DOCS)
    assert res["n_cases"] == len(C.EVAL_CASES)
    assert res["doc_map"]  # slug → id 映射

    # 幂等：再 seed（无 reset）→ skip
    res2 = await seed_eval_corpus(sqlite_session, TenantContext("default"))
    assert res2.get("skipped") is True

    # reset → 重建，用例数不变
    res3 = await seed_eval_corpus(sqlite_session, TenantContext("default"), reset=True)
    assert res3["n_cases"] == len(C.EVAL_CASES)


@pytest.mark.asyncio
async def test_eval_regression_gate(sqlite_session):
    await seed_eval_corpus(sqlite_session, TenantContext("default"))

    async def mock_generate(query, context, chunks):
        # 模拟"答案取自首个检索块"——faithfulness 应接近 1.0（完全源自上下文）
        return chunks[0].content if chunks else ""

    report = await run_eval(
        sqlite_session, TenantContext("default"), C.SCENE_ID_DEFAULT, generate=mock_generate
    )
    assert report["n_cases"] == len(C.EVAL_CASES)
    by_query = {row["query"]: row for row in report["cases"]}

    no_answer = [c for c in C.EVAL_CASES if "no_answer" in c.tags]
    answerable = [c for c in C.EVAL_CASES if "no_answer" not in c.tags]

    # 无答案：正确返回空（无假阳性误召回）
    for c in no_answer:
        row = by_query[c.query]
        assert row["n_retrieved"] == 0, f"无答案 case 误召回: {c.query}"
        assert row["recall@k"] == 0.0

    # 可答：期望文档进入 top-k（召回率高）
    recalls = [by_query[c.query]["recall@k"] for c in answerable]
    mean_recall = sum(recalls) / len(recalls)
    assert mean_recall >= 0.8, f"可答 case 平均召回过低: {mean_recall:.2f}"
    assert all(r >= 0.5 for r in recalls), "存在可答 case 召回 < 0.5"

    # 归一化不变式：recall@k / mrr / ndcg 必须落在 [0,1]。
    # 防回归"同文档多 chunk 被重复计入排名"导致 nDCG > 1（2026-07 §3 真实跑暴露）。
    for row in report["cases"]:
        for key in ("recall@k", "mrr", "ndcg"):
            assert 0.0 <= row[key] <= 1.0, f"{key} 越界 {row[key]} ({row['query']})"

    # bbox 溯源：预测区域命中真值（同段落 → IoU=1）
    for c in (c for c in C.EVAL_CASES if "bbox" in c.tags):
        assert by_query[c.query]["bbox_accuracy"] == 1.0, f"bbox 未命中: {c.query}"

    # 生成层：faithfulness 已计算；可答 case 答案源自上下文 → 接近 1.0
    for c in answerable:
        assert by_query[c.query]["faithfulness"] >= 0.99, f"faithfulness 异常: {c.query}"

    # 聚合报告含全部关键指标键
    for key in ("recall@k", "mrr", "ndcg", "citation_accuracy", "faithfulness"):
        assert key in report, f"聚合报告缺键: {key}"


@pytest.mark.asyncio
async def test_eval_without_generation_omits_faithfulness(sqlite_session):
    """不传 generate → 仅检索层指标，无 faithfulness 列（默认快路径）。"""
    await seed_eval_corpus(sqlite_session, TenantContext("default"))
    report = await run_eval(sqlite_session, TenantContext("default"), C.SCENE_ID_DEFAULT)
    assert report["n_cases"] == len(C.EVAL_CASES)
    assert "faithfulness" not in report  # 未生成 → 不聚合 faithfulness
    assert "recall@k" in report


@pytest.mark.asyncio
async def test_index_eval_corpus_skips_without_infra(sqlite_session):
    """离线无 infra（未 init_stores）→ index_eval_corpus 安全跳过，不报错、不改 DB。

    防回归：CLI --index 在无 Milvus/OpenSearch 时不应崩，BM25 本地兜底仍可评估。
    """
    await seed_eval_corpus(sqlite_session, TenantContext("default"))
    result = await index_eval_corpus(sqlite_session, TenantContext("default"))
    assert result.get("skipped") is True
    assert "infra" in result["reason"]


def test_eval_doc_filter_uses_json_path_on_postgres():
    """防回归：eval 文档过滤在 PG 方言下须用 `->>`（JSON 路径），不能退化成 LIKE。

    可移植 JSONB 类型（JSON.with_variant）的 `.contains()` 在 PG 上仍走基类 JSON
    Comparator → 生成 `meta LIKE '%' || JSONB || '%'` → 'Token "%" is invalid' 崩溃
    （2026-07 §3 真实跑暴露；离线 sqlite 走另一套实现测不到，故在此编译到 PG 方言断言）。
    """
    from sqlalchemy.dialects import postgresql

    from app.eval.seed import _eval_doc_filter

    sql = str(_eval_doc_filter().compile(dialect=postgresql.dialect()))
    assert "->>" in sql
    assert "LIKE" not in sql.upper()
