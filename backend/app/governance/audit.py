"""审计日志（设计书 §8）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.repositories import governance as gov_repo


async def log(
    session: AsyncSession, tenant: TenantContext, *, action: str,
    target: Optional[str] = None, actor: Optional[str] = None, detail: Optional[dict] = None,
) -> None:
    await gov_repo.log(session, tenant, action=action, target=target, actor=actor, detail=detail)
