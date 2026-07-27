"""评估与 A/B API（设计书 §9）：用例 CRUD、离线评估运行、A/B 反馈聚合。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx, require_roles
from app.core.tenant import TenantContext
from app.eval.runner import run_eval
from app.repositories import eval as eval_repo

router = APIRouter()


class EvalCaseIn(BaseModel):
    scene_id: str
    query: str
    expected_answer: Optional[str] = None
    expected_doc_ids: List[int] = Field(default_factory=list)
    expected_page: Optional[int] = None
    expected_bbox: Optional[List[float]] = None
    tags: List[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class EvalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scene_id: str
    query: str
    expected_answer: Optional[str] = None
    expected_doc_ids: List[int] = Field(default_factory=list)
    expected_page: Optional[int] = None
    expected_bbox: Optional[List[float]] = None


@router.post("/admin/eval/cases", response_model=EvalCaseOut)
async def create_case(
    req: EvalCaseIn,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    obj = await eval_repo.add_case(
        session, tenant,
        scene_id=req.scene_id, query=req.query, expected_answer=req.expected_answer,
        expected_doc_ids=req.expected_doc_ids, expected_page=req.expected_page,
        expected_bbox=req.expected_bbox, tags=req.tags, meta=req.meta,
    )
    await session.commit()
    return obj


@router.get("/admin/eval/cases", response_model=List[EvalCaseOut])
async def list_cases(
    scene_id: str,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    rows = await eval_repo.list_cases(session, tenant, scene_id)
    return rows


@router.delete("/admin/eval/cases/{case_id}")
async def delete_case(
    case_id: int,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    await eval_repo.delete_case(session, tenant, case_id)
    await session.commit()
    return {"ok": True}


@router.post("/admin/eval/{scene_id}/run")
async def run_scene_eval(
    scene_id: str,
    top_k: Optional[int] = None,
    tenant: TenantContext = Depends(require_roles("admin", "editor")),
    session: AsyncSession = Depends(get_session),
):
    """对该场景的评估集跑离线检索评估，返回聚合指标报告。"""
    return await run_eval(session, tenant, scene_id, top_k=top_k)


@router.get("/admin/ab/feedback")
async def ab_feedback(
    conversation_id: Optional[int] = None,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    """按 A/B 变体聚合反馈（点赞/点踩/消息数），用于效果对比。"""
    return await eval_repo.feedback_by_variant(session, tenant, conversation_id)
