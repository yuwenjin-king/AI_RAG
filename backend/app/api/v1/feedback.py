"""反馈 API（点赞/点踩/标注，效果评估闭环）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx, require_roles
from app.core.tenant import TenantContext
from app.repositories import governance as gov_repo
from app.schemas.governance import FeedbackCreate, FeedbackOut

router = APIRouter()


@router.post("/feedback", response_model=FeedbackOut)
async def create_feedback(
    req: FeedbackCreate,
    tenant: TenantContext = Depends(require_roles("admin", "editor", "viewer")),
    session: AsyncSession = Depends(get_session),
):
    obj = await gov_repo.add_feedback(
        session, tenant, message_id=req.message_id, rating=req.rating, comment=req.comment
    )
    await session.commit()
    return obj
