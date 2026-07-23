"""多租户上下文：从请求头解析 X-Tenant-Id，全链路透传。"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, Request

from app.core.config import settings

_current_tenant: ContextVar["TenantContext"] = ContextVar("current_tenant", default=None)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    role: Optional[str] = None  # 当前租户内角色（认证开启后取自 JWT，否则取自 X-Role 头）
    user_id: Optional[int] = None  # 认证用户 id（匿名为 None）

    @property
    def collection(self) -> str:
        if settings.collection_per_tenant:
            return settings.tenant_collection(self.tenant_id)
        return settings.collection_name

    @property
    def index(self) -> str:
        return settings.tenant_index(self.tenant_id)


def normalize_tenant(raw: str | None) -> str:
    return (raw or "").strip() or settings.default_tenant_id


async def get_tenant_ctx(
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias=settings.tenant_header),
    x_role: str | None = Header(default=None, alias=settings.role_header),
) -> TenantContext:
    """FastAPI 依赖：认证感知地解析租户并写入 ContextVar。

    auth_enabled=True 时强制 JWT，租户取自令牌（X-Tenant-Id 仅作成员租户切换）；
    auth_enabled=False 时信任 X-Tenant-Id（旧行为，本地/测试无密码可跑）。
    """
    from app.core.auth import resolve_tenant_ctx  # 延迟导入避免循环

    ctx = resolve_tenant_ctx(request.headers, x_tenant_id, x_role)
    _current_tenant.set(ctx)
    return ctx


def current_tenant() -> TenantContext:
    ctx = _current_tenant.get()
    if ctx is None:
        return TenantContext(tenant_id=settings.default_tenant_id)
    return ctx
