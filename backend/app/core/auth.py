"""认证与授权：身份解析、当前用户依赖、角色门禁（plan_three §1）。

设计：
- auth_enabled=False（默认）：信任 X-Tenant-Id / X-Role 头（本地/测试无密码可跑）。
- auth_enabled=True：强制 `Authorization: Bearer <JWT>`；effective tenant 取自令牌，
  X-Tenant-Id 仅用于在用户**所属租户**间切换（非成员 → 403）。租户由此不可伪造。

JWT 无状态（无每请求 DB 查询）；撤销需 denylist（v1 未实现，靠短有效期 + 改密 + 轮换 secret）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.security import TokenError, decode_access_token
from app.core.tenant import TenantContext, normalize_tenant

VALID_ROLES = {"admin", "editor", "viewer"}


@dataclass(frozen=True)
class CurrentUser:
    """解析后的当前用户（JWT 解码结果；auth_enabled=False 时为匿名 admin）。"""

    user_id: int
    username: str
    tenant_id: str  # 归属/默认租户
    role: str  # 默认租户内角色
    memberships: Mapping[str, str] = field(default_factory=dict)  # {tenant_id: role}
    authenticated: bool = True

    @property
    def member_tenants(self) -> set[str]:
        return {self.tenant_id, *self.memberships.keys()}

    def role_for(self, tenant_id: str) -> Optional[str]:
        if tenant_id == self.tenant_id:
            return self.role
        return self.memberships.get(tenant_id)


def _anonymous() -> CurrentUser:
    """auth_enabled=False 时的匿名身份（兼容旧的"信任头"开发模式）。"""
    return CurrentUser(
        user_id=0,
        username="anonymous",
        tenant_id=settings.default_tenant_id,
        role="admin",
        memberships={},
        authenticated=False,
    )


def authenticate(request_or_headers: Request | Mapping[str, str]) -> CurrentUser:
    """从请求头解析身份。auth_enabled=False → 匿名；True → 校验 JWT（失败 401）。"""
    if not settings.auth_enabled:
        return _anonymous()
    headers = request_or_headers.headers if hasattr(request_or_headers, "headers") else request_or_headers
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")
    try:
        user_id = int(claims.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid token: bad subject")
    memberships = claims.get("memberships") or {}
    if not isinstance(memberships, dict):
        memberships = {}
    role = str(claims.get("role") or "viewer")
    if role not in VALID_ROLES:
        role = "viewer"
    return CurrentUser(
        user_id=user_id,
        username=str(claims.get("username", "")),
        tenant_id=str(claims.get("tenant_id") or settings.default_tenant_id),
        role=role,
        memberships=memberships,
    )


def resolve_tenant_ctx(
    headers, x_tenant_id: Optional[str], x_role: Optional[str]
) -> TenantContext:
    """认证感知的租户上下文解析（get_tenant_ctx 调用；纯函数，便于单测）。

    - auth_enabled=True：租户取自令牌；显式 X-Tenant-Id 非成员 → 403；未指定 → 归属租户。
    - auth_enabled=False：信任 X-Tenant-Id（旧行为），role 取自 X-Role 头。
    """
    if not settings.auth_enabled:
        return TenantContext(tenant_id=normalize_tenant(x_tenant_id), role=x_role)

    user = authenticate(headers)  # 可能 401
    requested = normalize_tenant(x_tenant_id)
    if x_tenant_id and requested not in user.member_tenants:
        raise HTTPException(status_code=403, detail="forbidden: not a member of tenant")
    eff = requested if requested in user.member_tenants else user.tenant_id
    role = user.role_for(eff) or user.role
    return TenantContext(tenant_id=eff, role=role, user_id=user.user_id)


async def get_current_user(request: Request) -> CurrentUser:
    """FastAPI 依赖：返回当前用户（auth_enabled=False 时为匿名 admin）。"""
    return authenticate(request)


def require_roles(*allowed: str):
    """角色门禁依赖工厂。auth_enabled=False 时放行（兼容开发/测试）。

    用法：`_user = Depends(require_roles("admin", "editor"))`。
    注：此处 role 取自用户**默认租户**角色（v1）；切换租户时的细粒度由 get_tenant_ctx 处理。
    """

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not settings.auth_enabled:
            return user
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden: insufficient role")
        return user

    return _dep
