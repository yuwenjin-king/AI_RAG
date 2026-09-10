"""知识库管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx, require_roles
from app.core.exceptions import AppError
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
    try:
        # create 内部 flush，UNIQUE 冲突在 INSERT 即抛——须与 commit 同在保护内
        obj = await kb_repo.create(
            session, tenant, name=req.name, description=req.description,
            retrieval_config=req.retrieval_config, prompt_template_id=req.prompt_template_id,
        )
        await session.commit()
    except IntegrityError:
        # uq_kb_tenant_name：同租户重名（并发创建/前端重复提交）
        await session.rollback()
        raise AppError("同名知识库已存在", code="duplicate_knowledge_base", status_code=409)
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
    try:
        # update 内部 flush，改名冲突在 UPDATE 即抛
        obj = await kb_repo.update(session, tenant, kb_id, **req.model_dump(exclude_unset=True))
        await session.commit()
    except IntegrityError:
        # 改名撞同租户已有名称 → 409（而非 500）
        await session.rollback()
        raise AppError("同名知识库已存在", code="duplicate_knowledge_base", status_code=409)
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
