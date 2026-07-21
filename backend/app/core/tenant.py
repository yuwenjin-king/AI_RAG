"""多租户上下文：从请求头解析 X-Tenant-Id，全链路透传。"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Header, Request

from app.core.config import settings

_current_tenant: ContextVar["TenantContext"] = ContextVar("current_tenant", default=None)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str

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
) -> TenantContext:
    """FastAPI 依赖：解析租户并写入 ContextVar。"""
    tenant_id = normalize_tenant(x_tenant_id)
    ctx = TenantContext(tenant_id=tenant_id)
    _current_tenant.set(ctx)
    return ctx


def current_tenant() -> TenantContext:
    ctx = _current_tenant.get()
    if ctx is None:
        return TenantContext(tenant_id=settings.default_tenant_id)
    return ctx
