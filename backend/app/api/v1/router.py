"""v1 路由聚合。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    chat,
    conversations,
    documents,
    feedback,
    health,
    knowledge_bases,
    model_configs,
    tenants,
)
from app.api.v1.admin import scenes as admin_scenes
from app.api.v1.admin import eval as admin_eval
from app.api.v1.admin import audit as admin_audit

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(tenants.router, tags=["tenant"])
api_router.include_router(knowledge_bases.router, tags=["knowledge-base"])
api_router.include_router(documents.router, tags=["document"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(conversations.router, tags=["conversation"])
api_router.include_router(model_configs.router, tags=["model-config"])
api_router.include_router(feedback.router, tags=["feedback"])
api_router.include_router(admin_scenes.router, tags=["admin"])
api_router.include_router(admin_eval.router, tags=["admin"])
api_router.include_router(admin_audit.router, tags=["admin"])
