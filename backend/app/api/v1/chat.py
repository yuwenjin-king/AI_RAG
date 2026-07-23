"""对话问答 API（SSE 流式）+ 纯检索 API（检索与生成解耦）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_tenant_ctx
from app.core import ratelimit
from app.core.tenant import TenantContext
from app.schemas.chat import ChatRequest, RetrieveRequest, RetrieveResponse
from app.services import rag

router = APIRouter()


@router.post("/chat")
async def chat(
    req: ChatRequest,
    tenant: TenantContext = Depends(get_tenant_ctx),
):
    """流式问答（SSE）。事件：meta / citations / token / done。

    role 取自认证上下文（auth_enabled=True 时来自 JWT，不可伪造；否则来自 X-Role 头）。
    """
    # 成本管控：per-tenant 限流（设计书 §4.5）
    if not await ratelimit.allow(tenant.tenant_id, endpoint="chat"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    async def event_gen():
        async for evt in rag.chat_stream(tenant, req, role=tenant.role):
            yield {
                "event": evt["event"],
                "data": json.dumps(evt["data"], ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    req: RetrieveRequest,
    tenant: TenantContext = Depends(get_tenant_ctx),
):
    """纯检索（不生成），供其他系统复用。"""
    chat_req = ChatRequest(
        query=req.query,
        knowledge_base_id=req.knowledge_base_id,
        scene_id=req.scene_id,
        top_k=req.top_k,
    )
    return await rag.retrieve_only(tenant, chat_req, role=tenant.role)
