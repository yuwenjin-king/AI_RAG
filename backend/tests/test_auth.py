"""认证授权测试（plan_three §1）。

策略：纯函数/仓储直调（不经过 HTTP），与项目离线测试惯例一致。
- security：密码哈希往返 / JWT 签发-校验-防篡改-过期。
- auth.resolve_tenant_ctx：auth_enabled 开/关、无 token(401)、有效 token、
  跨租户非成员(403)、成员租户切换。
- require_roles：角色门禁 + auth_enabled=False 放行。
- 仓储 + 登录链路：建用户→取用户→验码→签 token。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import auth as auth_mod
from app.core.auth import CurrentUser, require_roles, resolve_tenant_ctx
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.repositories import users as user_repo


def _expect_status(code: int):
    """返回 pytest.raises 上下文，并在退出时断言 HTTPException.status_code。"""
    return pytest.raises(HTTPException)


def _assert_status(exc_info, code: int) -> None:
    assert exc_info.value.status_code == code


# ===== security =====
def test_password_hash_roundtrip():
    h = hash_password("s3cret!")
    assert h != "s3cret!"
    assert verify_password("s3cret!", h)
    assert not verify_password("wrong", h)


def test_password_unique_salts():
    assert hash_password("same") != hash_password("same")


def test_jwt_roundtrip():
    tok = create_access_token({"sub": "7", "username": "u", "tenant_id": "acme", "role": "editor"})
    claims = decode_access_token(tok)
    assert claims["sub"] == "7"
    assert claims["tenant_id"] == "acme"
    assert claims["role"] == "editor"


def test_jwt_bad_signature_rejected():
    tok = create_access_token({"sub": "1"})
    header, payload, sig = tok.split(".")
    # 翻转签名末字符（保持 base64url 合法长度）→ HMAC 校验失败
    flip = "B" if sig[-1] != "B" else "C"
    tampered = f"{header}.{payload}.{sig[:-1]}{flip}"
    with pytest.raises(TokenError):
        decode_access_token(tampered)


def test_jwt_expired_rejected():
    tok = create_access_token({"sub": "1"}, expires_minutes=-1)  # 已过期
    with pytest.raises(TokenError):
        decode_access_token(tok)


def test_jwt_malformed_rejected():
    with pytest.raises(TokenError):
        decode_access_token("not.a.valid")


# ===== resolve_tenant_ctx =====
def test_resolve_auth_off_trusts_headers(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", False)
    ctx = resolve_tenant_ctx({}, "acme", "viewer")
    assert ctx.tenant_id == "acme"
    assert ctx.role == "viewer"
    assert ctx.user_id is None  # 匿名


def test_resolve_auth_on_no_token_401(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    with _expect_status(401) as ei:
        resolve_tenant_ctx({}, None, None)
    _assert_status(ei, 401)


def test_resolve_auth_on_valid_token_uses_home(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    tok = create_access_token(
        {"sub": "1", "username": "u", "tenant_id": "acme", "role": "editor",
         "memberships": {"acme": "editor", "beta": "viewer"}}
    )
    ctx = resolve_tenant_ctx({"authorization": f"Bearer {tok}"}, None, None)
    assert ctx.tenant_id == "acme"
    assert ctx.role == "editor"
    assert ctx.user_id == 1


def test_resolve_auth_on_member_switch(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    tok = create_access_token(
        {"sub": "1", "username": "u", "tenant_id": "acme", "role": "editor",
         "memberships": {"acme": "editor", "beta": "viewer"}}
    )
    ctx = resolve_tenant_ctx({"authorization": f"Bearer {tok}"}, "beta", None)
    assert ctx.tenant_id == "beta"
    assert ctx.role == "viewer"  # beta 成员角色


def test_resolve_auth_on_cross_tenant_403(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    tok = create_access_token(
        {"sub": "1", "username": "u", "tenant_id": "acme", "role": "editor",
         "memberships": {"acme": "editor"}}
    )
    with _expect_status(403) as ei:
        resolve_tenant_ctx({"authorization": f"Bearer {tok}"}, "other-tenant", None)
    _assert_status(ei, 403)


# ===== require_roles =====
@pytest.mark.asyncio
async def test_require_roles_denies_viewer(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    dep = require_roles("admin", "editor")
    viewer = CurrentUser(user_id=1, username="v", tenant_id="acme", role="viewer")
    with _expect_status(403) as ei:
        await dep(user=viewer)
    _assert_status(ei, 403)


@pytest.mark.asyncio
async def test_require_roles_allows_editor(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", True)
    dep = require_roles("admin", "editor")
    editor = CurrentUser(user_id=1, username="e", tenant_id="acme", role="editor")
    got = await dep(user=editor)
    assert got.role == "editor"


@pytest.mark.asyncio
async def test_require_roles_passthrough_when_auth_off(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "auth_enabled", False)
    dep = require_roles("admin")
    viewer = CurrentUser(user_id=1, username="v", tenant_id="acme", role="viewer")
    got = await dep(user=viewer)  # 不应抛
    assert got is viewer


# ===== 仓储 + 登录链路 =====
async def test_user_repo_and_login_flow(sqlite_session):
    await user_repo.ensure_tenant(sqlite_session, "acme")
    await user_repo.create_user(
        sqlite_session,
        username="alice",
        password="pw123",
        memberships=[("acme", "editor")],
    )
    await sqlite_session.commit()

    user = await user_repo.get_user_with_memberships(sqlite_session, "alice")
    assert user is not None
    assert verify_password("pw123", user.password_hash)
    assert not verify_password("nope", user.password_hash)
    memberships = {m.tenant_id: m.role for m in user.memberships}
    assert memberships == {"acme": "editor"}

    # 模拟 /auth/login 签 token
    home_tenant = next(iter(memberships), "default")
    token = create_access_token(
        {"sub": str(user.id), "username": user.username,
         "tenant_id": home_tenant, "role": memberships[home_tenant], "memberships": memberships}
    )
    claims = decode_access_token(token)
    assert claims["username"] == "alice"
    assert claims["tenant_id"] == "acme"


async def test_seed_admin_idempotent(sqlite_session):
    assert await user_repo.seed_admin_if_absent(sqlite_session) is True
    assert await user_repo.seed_admin_if_absent(sqlite_session) is False  # 幂等
    admin = await user_repo.get_user_with_memberships(sqlite_session, "admin")
    assert admin is not None
    assert {m.tenant_id: m.role for m in admin.memberships} == {"default": "admin"}
