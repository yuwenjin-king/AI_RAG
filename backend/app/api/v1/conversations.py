"""会话历史 API（多轮）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx
from app.core.tenant import TenantContext
from app.repositories import conversation as conv_repo
from app.schemas.chat import ConversationOut, MessageOut

router = APIRouter()


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    conv, msgs = await conv_repo.get_with_messages(session, tenant, conversation_id)
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        knowledge_base_id=conv.knowledge_base_id,
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content,
                citations=m.citations or [], degraded=m.degraded or [],
            )
            for m in msgs
        ],
    )
