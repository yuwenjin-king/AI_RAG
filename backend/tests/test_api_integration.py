"""HTTP 层集成测试：直接调用 handler 函数 + sqlite session（不经 TestClient/SSE）。

覆盖 API↔repo↔schema↔审计 的全栈接线（response_model 序列化、租户隔离、审计落库等），
捕捉单元测试难以发现的装配类缺陷。
"""
import pytest

from app.api.v1 import documents as doc_api
from app.api.v1 import feedback as fb_api
from app.api.v1 import knowledge_bases as kb_api
from app.api.v1 import model_configs as mc_api
from app.api.v1 import tenants as t_api
from app.api.v1.admin import audit as au_api
from app.api.v1.admin import scenes as sc_api
from app.core.config import settings as cfg
from app.core.tenant import TenantContext
from app.repositories import document as doc_repo
from app.schemas.entities import KnowledgeBaseCreate, UploadUrlRequest
from app.schemas.governance import FeedbackCreate, ModelConfigCreate, SceneConfigCreate


@pytest.mark.asyncio
async def test_tenants_me(sqlite_session):
    t = await t_api.me(tenant=TenantContext("A"), session=sqlite_session)
    assert t.tenant_id == "A"


@pytest.mark.asyncio
async def test_kb_crud_and_isolation(sqlite_session):
    tenant_a = TenantContext("A")
    kb = await kb_api.create_kb(
        KnowledgeBaseCreate(name="KB1", description="d"), tenant=tenant_a, session=sqlite_session
    )
    assert kb.id and kb.name == "KB1"

    page = await kb_api.list_kbs(page=1, page_size=10, tenant=tenant_a, session=sqlite_session)
    assert page.total >= 1

    got = await kb_api.get_kb(kb.id, tenant=tenant_a, session=sqlite_session)
    assert got.id == kb.id

    # 租户隔离：B 看不到 A 的 KB
    page_b = await kb_api.list_kbs(page=1, page_size=10, tenant=TenantContext("B"), session=sqlite_session)
    assert all(k.tenant_id == "B" for k in page_b.items)

    await kb_api.delete_kb(kb.id, tenant=tenant_a, session=sqlite_session)


@pytest.mark.asyncio
async def test_documents_upload_url_list_locate(sqlite_session, monkeypatch):
    monkeypatch.setattr(cfg, "sync_ingest_fallback", False)
    tenant = TenantContext("A")
    resp = await doc_api.create_upload_url(
        UploadUrlRequest(filename="a.txt", content_type="text/plain"),
        tenant=tenant, session=sqlite_session,
    )
    assert resp.doc_id and resp.direct_upload_url  # MinIO 未初始化 → 走直传入口

    page = await doc_api.list_documents(tenant=tenant, session=sqlite_session)
    assert page.total >= 1

    # 追加 chunk 后测溯源定位
    chunk = (
        await doc_repo.add_chunks(sqlite_session, [{
            "tenant_id": "A", "document_id": resp.doc_id, "ordinal": 0,
            "content": "x", "page_no": 2, "bbox": [0.1, 0.1, 0.2, 0.2],
        }])
    )[0]
    await sqlite_session.commit()
    loc = await doc_api.locate(resp.doc_id, chunk.id, tenant=tenant, session=sqlite_session)
    assert loc.page_no == 2 and loc.bbox == [0.1, 0.1, 0.2, 0.2]


@pytest.mark.asyncio
async def test_feedback(sqlite_session):
    fb = await fb_api.create_feedback(
        FeedbackCreate(rating=1, comment="good"), tenant=TenantContext("A"), session=sqlite_session
    )
    assert fb.id and fb.rating == 1


@pytest.mark.asyncio
async def test_model_config_default(sqlite_session):
    mc = await mc_api.create_model_config(
        ModelConfigCreate(kind="llm", name="default", model="glm-4-flash", is_default=True),
        tenant=TenantContext("A"), session=sqlite_session,
    )
    assert mc.id
    d = await mc_api.get_default("llm", tenant=TenantContext("A"), session=sqlite_session)
    assert d and d.model == "glm-4-flash"


@pytest.mark.asyncio
async def test_scene_upsert_get_and_audit(sqlite_session):
    tenant = TenantContext("A")
    sc = await sc_api.upsert_scene(
        "s1", SceneConfigCreate(scene_id="s1", name="S1"),
        tenant=tenant, session=sqlite_session,
    )
    assert sc.scene_id == "s1"
    got = await sc_api.get_scene("s1", tenant=tenant, session=sqlite_session)
    assert got and got.scene_id == "s1"

    # 审计：scene.upsert 应落库并可查
    rows = await au_api.list_audit(tenant=tenant, session=sqlite_session)
    assert any(r.action == "scene.upsert" for r in rows)
