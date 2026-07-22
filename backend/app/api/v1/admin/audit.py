"""审计日志查询 API（设计书 §8）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx
from app.core.tenant import TenantContext
from app.repositories import governance as gov_repo

router = APIRouter()


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    target: Optional[str] = None
    actor: Optional[str] = None
    detail: dict = {}
    created_at: Optional[str] = None


@router.get("/admin/audit", response_model=List[AuditOut])
async def list_audit(
    action: Optional[str] = None,
    limit: int = 200,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    rows = await gov_repo.list_audit(session, tenant, action=action, limit=limit)
    return rows
