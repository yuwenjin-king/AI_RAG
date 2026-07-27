"""场景配置 API（四要素：知识库 + 检索策略 + Prompt + 权限）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx, require_roles
from app.core.tenant import TenantContext
from app.governance import audit
from app.repositories import governance as gov_repo
from app.schemas.governance import SceneConfigCreate, SceneConfigOut

router = APIRouter()


@router.put("/admin/scenes/{scene_id}", response_model=SceneConfigOut)
async def upsert_scene(
    scene_id: str,
    req: SceneConfigCreate,
    tenant: TenantContext = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_session),
):
    fields = req.model_dump()
    fields["scene_id"] = scene_id
    obj = await gov_repo.upsert_scene(session, tenant, **fields)
    await audit.log(session, tenant, action="scene.upsert", target=scene_id, detail={"name": req.name})
    await session.commit()
    return obj


@router.get("/admin/scenes/{scene_id}", response_model=SceneConfigOut | None)
async def get_scene(
    scene_id: str,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    return await gov_repo.get_scene(session, tenant, scene_id)
