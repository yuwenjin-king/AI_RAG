"""端到端角色门禁测试（plan_four §1）。

策略：构建最小 FastAPI app（仅含非-SSE 路由），用真 JWT 经 ASGI 走完整依赖链
（get_tenant_ctx → JWT 解码 → require_roles 角色校验），证明门禁确实接入了路由：

- 写接口 viewer → 403；editor/admin → 通过（200）
- admin-only 接口（scenes / model-configs / audit）：editor → 403；admin → 通过
- 无 token → 401；跨租户非成员（X-Tenant-Id 指向非成员租户）→ 403
- 读接口 viewer → 200（读不受门禁，仅租户隔离）

chat/retrieve 经 sse_starlette，本机不可 import（与 starlette 版本冲突），其角色门禁由
test_auth.py 的 require_roles 单测覆盖；离线 handler 行为由 test_api_integration.py 覆盖
（直接调函数，绕过 DI，不受本改动影响）。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1 import knowledge_bases as kb_api
from app.api.v1 import model_configs as mc_api
from app.api.v1.admin import audit as au_api, eval as ev_api, scenes as sc_api
from app.core.config import settings
from app.core.security import create_access_token
from app.db import models  # noqa: F401  注册所有表
from app.db.database import Base, get_session


def _token(role: str, tenant: str = "acme", memberships: dict | None = None) -> str:
    """签发测试用 JWT。memberships 决定用户可切换的成员租户。"""
    return create_access_token({
        "sub": "1",
        "username": role,
        "tenant_id": tenant,
        "role": role,
        "memberships": memberships if memberships is not None else {tenant: role},
    })


def _hdr(token: str | None, tenant: str | None = None) -> dict:
    h: dict = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


@pytest_asyncio.fixture
async def app_client(monkeypatch):
    """最小 ASGI app + sqlite，auth_enabled=True。"""
    monkeypatch.setattr(settings, "auth_enabled", True)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(kb_api.router)
    app.include_router(sc_api.router)
    app.include_router(au_api.router)
    app.include_router(mc_api.router)
    app.include_router(ev_api.router)

    async def _get_session():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_session] = _get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


# ===== 无 token / 跨租户 =====
@pytest.mark.asyncio
async def test_no_token_write_returns_401(app_client):
    r = await app_client.post("/knowledge-bases", json={"name": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cross_tenant_non_member_returns_403(app_client):
    # 归属 acme，X-Tenant-Id 切到非成员租户 zeta
    tok = _token("admin", tenant="acme", memberships={"acme": "admin"})
    r = await app_client.post(
        "/knowledge-bases", json={"name": "x"}, headers=_hdr(tok, tenant="zeta")
    )
    assert r.status_code == 403


# ===== 写接口：viewer 403 / editor+admin 200 =====
@pytest.mark.asyncio
async def test_viewer_cannot_create_kb(app_client):
    r = await app_client.post("/knowledge-bases", json={"name": "x"}, headers=_hdr(_token("viewer")))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_create_kb(app_client):
    r = await app_client.post("/knowledge-bases", json={"name": "x"}, headers=_hdr(_token("editor")))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_create_kb(app_client):
    r = await app_client.post("/knowledge-bases", json={"name": "y"}, headers=_hdr(_token("admin")))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_can_read_kb(app_client):
    r = await app_client.get("/knowledge-bases", headers=_hdr(_token("viewer")))
    assert r.status_code == 200  # 读不受门禁


# ===== admin-only 接口：editor 403 / admin 200 =====
@pytest.mark.asyncio
async def test_editor_cannot_upsert_scene(app_client):
    r = await app_client.put(
        "/admin/scenes/s1", json={"scene_id": "s1", "name": "s1"}, headers=_hdr(_token("editor"))
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_upsert_scene(app_client):
    r = await app_client.put(
        "/admin/scenes/s1", json={"scene_id": "s1", "name": "s1"}, headers=_hdr(_token("admin"))
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_editor_cannot_create_model_config(app_client):
    r = await app_client.post(
        "/model-configs",
        json={"kind": "llm", "name": "n", "model": "m"},
        headers=_hdr(_token("editor")),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_model_config(app_client):
    r = await app_client.post(
        "/model-configs",
        json={"kind": "llm", "name": "n", "model": "m"},
        headers=_hdr(_token("admin")),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_view_audit(app_client):
    r = await app_client.get("/admin/audit", headers=_hdr(_token("viewer")))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_view_audit(app_client):
    r = await app_client.get("/admin/audit", headers=_hdr(_token("admin")))
    assert r.status_code == 200


# ===== eval：editor 可管 case（admin,editor）=====
@pytest.mark.asyncio
async def test_viewer_cannot_create_eval_case(app_client):
    r = await app_client.post(
        "/admin/eval/cases",
        json={"scene_id": "s1", "query": "q"},
        headers=_hdr(_token("viewer")),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_create_eval_case(app_client):
    r = await app_client.post(
        "/admin/eval/cases",
        json={"scene_id": "s1", "query": "q"},
        headers=_hdr(_token("editor")),
    )
    assert r.status_code == 200
