"""多租户隔离：keyword 召回（本地 BM25 兜底）必须仅返回当前租户的 chunk。"""
import pytest

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.services.retrieval import keyword


@pytest.mark.asyncio
async def test_keyword_recall_tenant_isolation(sqlite_session):
    s = sqlite_session

    dA = Document(tenant_id="A", title="A", object_key="a", status="indexed")
    s.add(dA)
    await s.flush()
    s.add(Chunk(tenant_id="A", document_id=dA.id, ordinal=0, content="apple banana recipe"))

    dB = Document(tenant_id="B", title="B", object_key="b", status="indexed")
    s.add(dB)
    await s.flush()
    s.add(Chunk(tenant_id="B", document_id=dB.id, ordinal=0, content="apple banana secret"))
    await s.commit()

    hits, degraded = await keyword.keyword_recall(s, TenantContext("A"), "apple banana", 10)
    assert hits, "应召回租户 A 的 chunk"
    assert all(h["doc_id"] == dA.id for h in hits), "不得越权返回租户 B 的 chunk"
    # 测试环境未初始化 OpenSearch → 必然走本地兜底降级
    assert any("keyword" in d for d in degraded)
