"""检索编排端到端（sqlite + 本地 BM25 兜底 + 父子 Small-to-Big 回溯）。"""
import pytest

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.services.retrieval import orchestrator


@pytest.mark.asyncio
async def test_retrieve_parent_child_context_expansion(sqlite_session):
    s = sqlite_session
    doc = Document(
        tenant_id="A", title="Manual", object_key="k",
        content_type="text/plain", status="indexed",
    )
    s.add(doc)
    await s.flush()

    # 父块：不含查询词（仅作上下文）
    parent = Chunk(
        tenant_id="A", document_id=doc.id, ordinal=0,
        content="The widget assembly procedure is detailed in section four.",
        parent_chunk_id=None,
    )
    s.add(parent)
    await s.flush()
    # 子块：含查询词，精确溯源到第 3 页某区域
    child = Chunk(
        tenant_id="A", document_id=doc.id, ordinal=1,
        content="connect using the blue cable to the power module",
        page_no=3, bbox=[0.1, 0.1, 0.3, 0.3], parent_chunk_id=parent.id,
    )
    s.add(child)
    await s.commit()

    res = await orchestrator.retrieve(s, TenantContext("A"), "blue cable")

    assert res.chunks, "本地 BM25 应召回子块"
    top = res.chunks[0]
    assert top.parent_chunk_id == parent.id
    # Small-to-Big：生成上下文回溯到父块（父块不含查询词，证明是回溯而非子块自身）
    assert "widget assembly" in top.context
    # 引用仍精确到子块页码/bbox
    assert top.page_no == 3 and top.bbox == [0.1, 0.1, 0.3, 0.3]
    # 无 Milvus/OpenSearch → 必然降级
    assert any("vector" in d or "keyword" in d for d in res.degraded)
