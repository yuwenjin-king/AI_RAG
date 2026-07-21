"""租户仓储。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import TenantModel


async def get_or_create(session: AsyncSession, tenant: TenantContext) -> TenantModel:
    obj = (
        await session.execute(
            select(TenantModel).where(TenantModel.tenant_id == tenant.tenant_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        obj = TenantModel(tenant_id=tenant.tenant_id, name=tenant.tenant_id, settings={})
        session.add(obj)
        await session.flush()
    return obj
