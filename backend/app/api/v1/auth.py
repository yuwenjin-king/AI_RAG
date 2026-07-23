"""认证 API：登录（签发 JWT）/ 当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.repositories import users as user_repo
from app.schemas.auth import LoginRequest

router = APIRouter()


@router.post("/auth/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    """用户名密码 → JWT。返回 token 及归属租户/角色（前端据此切换租户上下文）。"""
    user = await user_repo.get_user_with_memberships(session, body.username)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    memberships = {m.tenant_id: m.role for m in user.memberships}
    home_tenant = next(iter(memberships), settings.default_tenant_id)
    home_role = memberships.get(home_tenant, "viewer")
    token = create_access_token(
        {
            "sub": str(user.id),
            "username": user.username,
            "tenant_id": home_tenant,
            "role": home_role,
            "memberships": memberships,
        }
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "tenant_id": home_tenant,
        "role": home_role,
        "memberships": memberships,
    }


@router.get("/auth/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    """返回当前用户（auth_enabled=False 时为匿名 admin）。"""
    return {
        "user_id": user.user_id,
        "username": user.username,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "memberships": dict(user.memberships),
        "authenticated": user.authenticated,
    }
