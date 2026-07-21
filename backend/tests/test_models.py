"""schema 冒烟：在 sqlite 上建表 + 读写，验证模型可移植与 JSON 溯源字段。"""
import pytest
from sqlalchemy import select

from app.db.models import Chunk, Document, KnowledgeBase, TenantModel


@pytest.mark.asyncio
async def test_schema_roundtrip(sqlite_session):
    s = sqlite_session
    t = TenantModel(tenant_id="t1", name="T1", settings={"k": "v"})
    s.add(t)
    await s.flush()

    kb = KnowledgeBase(tenant_id="t1", name="KB1", retrieval_config={"final_topk": 5})
    s.add(kb)
    await s.flush()

    doc = Document(
        tenant_id="t1", knowledge_base_id=kb.id, title="Doc", object_key="k",
        content_type="text/plain", status="pending", meta={"pages": 3},
    )
    s.add(doc)
    await s.flush()

    ch = Chunk(
        tenant_id="t1", document_id=doc.id, ordinal=0, content="hello",
        page_no=2, bbox=[0.1, 0.1, 0.2, 0.2],
    )
    s.add(ch)
    await s.commit()

    got = (await s.execute(select(Chunk).where(Chunk.id == ch.id))).scalar_one()
    assert got.page_no == 2
    assert got.bbox == [0.1, 0.1, 0.2, 0.2]  # JSON 字段可读写

    kb_got = (await s.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb.id))).scalar_one()
    assert kb_got.retrieval_config == {"final_topk": 5}
