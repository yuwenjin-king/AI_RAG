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


async def purge_expired(session: AsyncSession, *, retention_days: Optional[int] = None) -> int:
    """删除超过保留期（settings.audit_retention_days，默认 90 天）的审计日志。

    调用点：worker 启动清扫 + `make audit-purge`。合规保留期是全局策略，跨租户执行。
    """
    return await gov_repo.purge_expired(session, retention_days=retention_days)
