"""租户 API（确保当前租户记录存在）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx
from app.core.tenant import TenantContext
from app.repositories import tenant as tenant_repo
from app.schemas.entities import TenantOut

router = APIRouter()


@router.get("/tenants/me", response_model=TenantOut)
async def me(
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    obj = await tenant_repo.get_or_create(session, tenant)
    await session.commit()
    return obj
