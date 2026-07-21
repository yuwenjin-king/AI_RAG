"""会话 / 消息仓储（多轮对话上下文）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.db.models import Conversation, Message, Role


async def get_or_create(
    session: AsyncSession, tenant: TenantContext, *,
    conversation_id: Optional[int], knowledge_base_id: Optional[int] = None,
    title: Optional[str] = None,
) -> Conversation:
    if conversation_id:
        obj = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if obj is not None:
            return obj
    obj = Conversation(
        tenant_id=tenant.tenant_id, knowledge_base_id=knowledge_base_id, title=title,
    )
    session.add(obj)
    await session.flush()
    return obj


async def add_message(
    session: AsyncSession, tenant: TenantContext, conversation_id: int, *,
    role: Role, content: str, citations: Optional[list] = None, degraded: Optional[list] = None,
) -> Message:
    msg = Message(
        tenant_id=tenant.tenant_id, conversation_id=conversation_id, role=role.value,
        content=content, citations=citations or [], degraded=degraded or [],
    )
    session.add(msg)
    await session.flush()
    return msg


async def history(
    session: AsyncSession, tenant: TenantContext, conversation_id: int, limit: int = 10
) -> list[Message]:
    return list(
        (
            await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.tenant_id == tenant.tenant_id,
                )
                .order_by(Message.id.desc())
                .limit(limit)
            )
        ).scalars().all()[::-1]
    )


async def get_with_messages(
    session: AsyncSession, tenant: TenantContext, conversation_id: int
) -> tuple[Conversation, list[Message]]:
    obj = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError(f"conversation {conversation_id} not found")
    msgs = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
        )
    ).scalars().all()
    return obj, list(msgs)
