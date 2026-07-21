"""模型配置 API（LLM / Embedding / Rerank 可插拔）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx
from app.core.tenant import TenantContext
from app.repositories import governance as gov_repo
from app.schemas.governance import ModelConfigCreate, ModelConfigOut

router = APIRouter()


@router.post("/model-configs", response_model=ModelConfigOut)
async def create_model_config(
    req: ModelConfigCreate,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    obj = await gov_repo.upsert_model_config(
        session, tenant, kind=req.kind, name=req.name, provider=req.provider,
        model=req.model, base_url=req.base_url, api_key_ref=req.api_key_ref,
        params=req.params, is_default=req.is_default,
    )
    await session.commit()
    return obj


@router.get("/model-configs/{kind}/default", response_model=ModelConfigOut | None)
async def get_default(
    kind: str,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    return await gov_repo.default_model(session, tenant, kind)
