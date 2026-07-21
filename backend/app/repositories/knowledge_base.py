"""知识库仓储（租户隔离）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.db.models import KnowledgeBase


async def create(
    session: AsyncSession, tenant: TenantContext, *, name: str, description: str = "",
    retrieval_config: Optional[dict] = None, prompt_template_id: Optional[str] = None,
) -> KnowledgeBase:
    kb = KnowledgeBase(
        tenant_id=tenant.tenant_id, name=name, description=description,
        retrieval_config=retrieval_config or {}, prompt_template_id=prompt_template_id,
    )
    session.add(kb)
    await session.flush()
    return kb


async def get(session: AsyncSession, tenant: TenantContext, kb_id: int) -> KnowledgeBase:
    obj = (
        await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant.tenant_id
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError(f"knowledge_base {kb_id} not found")
    return obj


async def list_kbs(
    session: AsyncSession, tenant: TenantContext, *, page: int = 1, page_size: int = 50
):
    base = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant.tenant_id)
    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(KnowledgeBase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def update(session: AsyncSession, tenant: TenantContext, kb_id: int, **fields) -> KnowledgeBase:
    kb = await get(session, tenant, kb_id)
    for k, v in fields.items():
        if v is not None:
            setattr(kb, k, v)
    await session.flush()
    return kb


async def delete(session: AsyncSession, tenant: TenantContext, kb_id: int) -> None:
    kb = await get(session, tenant, kb_id)
    await session.delete(kb)
    await session.flush()
