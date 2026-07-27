"""知识库管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx, require_roles
from app.core.tenant import TenantContext
from app.repositories import knowledge_base as kb_repo
from app.schemas.common import Page
from app.schemas.entities import (
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)

router = APIRouter()


@router.post("/knowledge-bases", response_model=KnowledgeBaseOut)
async def create_kb(
    req: KnowledgeBaseCreate,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    obj = await kb_repo.create(
        session, tenant, name=req.name, description=req.description,
        retrieval_config=req.retrieval_config, prompt_template_id=req.prompt_template_id,
    )
    await session.commit()
    return obj


@router.get("/knowledge-bases", response_model=Page[KnowledgeBaseOut])
async def list_kbs(
    page: int = 1,
    page_size: int = 50,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    rows, total = await kb_repo.list_kbs(session, tenant, page=page, page_size=page_size)
    return Page(items=rows, total=total, page=page, page_size=page_size)


@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut)
async def get_kb(
    kb_id: int,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    return await kb_repo.get(session, tenant, kb_id)


@router.put("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut)
async def update_kb(
    kb_id: int,
    req: KnowledgeBaseUpdate,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    obj = await kb_repo.update(session, tenant, kb_id, **req.model_dump(exclude_unset=True))
    await session.commit()
    return obj


@router.delete("/knowledge-bases/{kb_id}")
async def delete_kb(
    kb_id: int,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    await kb_repo.delete(session, tenant, kb_id)
    await session.commit()
    return {"ok": True}
