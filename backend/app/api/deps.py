"""依赖注入入口：re-export 常用依赖，路由中通过 Depends 使用。"""
from __future__ import annotations

from app.core.tenant import TenantContext, get_tenant_ctx
from app.db.database import get_session

__all__ = ["get_tenant_ctx", "TenantContext", "get_session"]
