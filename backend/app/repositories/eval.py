"""评估用例仓储 + A/B 反馈聚合。"""
from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import EvalCase, Feedback, Message


async def add_case(
    session: AsyncSession, tenant: TenantContext, *,
    scene_id: str, query: str, expected_answer: Optional[str] = None,
    expected_doc_ids: Optional[list] = None, expected_page: Optional[int] = None,
    expected_bbox: Optional[list] = None, tags: Optional[list] = None, meta: Optional[dict] = None,
) -> EvalCase:
    obj = EvalCase(
        tenant_id=tenant.tenant_id, scene_id=scene_id, query=query,
        expected_answer=expected_answer, expected_doc_ids=expected_doc_ids or [],
        expected_page=expected_page, expected_bbox=expected_bbox,
        tags=tags or [], meta=meta or {},
    )
    session.add(obj)
    await session.flush()
    return obj


async def list_cases(
    session: AsyncSession, tenant: TenantContext, scene_id: str, *, limit: int = 1000
) -> List[EvalCase]:
    return list(
        (
            await session.execute(
                select(EvalCase)
                .where(EvalCase.tenant_id == tenant.tenant_id, EvalCase.scene_id == scene_id)
                .order_by(EvalCase.id.asc())
                .limit(limit)
            )
        ).scalars().all()
    )


async def delete_case(session: AsyncSession, tenant: TenantContext, case_id: int) -> None:
    obj = (
        await session.execute(
            select(EvalCase).where(
                EvalCase.id == case_id, EvalCase.tenant_id == tenant.tenant_id
            )
        )
    ).scalar_one_or_none()
    if obj is not None:
        await session.delete(obj)
        await session.flush()


async def feedback_by_variant(
    session: AsyncSession, tenant: TenantContext, conversation_id: Optional[int] = None
) -> List[dict]:
    """聚合各 A/B 变体的反馈（点赞/点踩/数），用于效果对比。

    变体取自 message.meta.variant；按变体汇总 feedback.rating（+1/-1）。
    """
    stmt = (
        select(Message.meta, Feedback.rating)
        .join(Feedback, Feedback.message_id == Message.id, isouter=True)
        .where(Message.tenant_id == tenant.tenant_id, Message.role == "assistant")
    )
    if conversation_id is not None:
        stmt = stmt.where(Message.conversation_id == conversation_id)
    rows = (await session.execute(stmt)).all()

    agg: dict[str, dict[str, Any]] = {}
    for meta, rating in rows:
        variant = (meta or {}).get("variant", "default")
        slot = agg.setdefault(variant, {"variant": variant, "messages": 0, "likes": 0, "dislikes": 0})
        slot["messages"] += 1
        if rating == 1:
            slot["likes"] += 1
        elif rating == -1:
            slot["dislikes"] += 1
    return list(agg.values())
