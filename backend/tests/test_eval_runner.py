"""评估 runner 端到端（sqlite + 本地 BM25 兜底）。"""
import pytest

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.eval.runner import run_eval
from app.repositories import eval as eval_repo


@pytest.mark.asyncio
async def test_run_eval_no_cases(sqlite_session):
    report = await run_eval(sqlite_session, TenantContext("A"), "empty-scene")
    assert report["n_cases"] == 0


@pytest.mark.asyncio
async def test_run_eval_metrics(sqlite_session):
    s = sqlite_session
    doc = Document(
        tenant_id="A", title="Manual", object_key="a",
        content_type="text/plain", status="indexed",
    )
    s.add(doc)
    await s.flush()
    s.add(Chunk(tenant_id="A", document_id=doc.id, ordinal=0, content="alpha beta gamma"))
    await s.flush()
    await eval_repo.add_case(
        s, TenantContext("A"), scene_id="s1", query="alpha",
        expected_doc_ids=[doc.id],
        expected_page=1, expected_bbox=[0.1, 0.1, 0.3, 0.3],
    )
    await s.commit()

    report = await run_eval(s, TenantContext("A"), "s1", top_k=5)
    assert report["n_cases"] == 1
    assert report["recall@k"] == 1.0      # 唯一相关文档被召回
    assert report["mrr"] == 1.0
    assert report["ndcg"] == 1.0
    assert report["citation_accuracy"] == 1.0
    assert report["cases"][0]["query"] == "alpha"
