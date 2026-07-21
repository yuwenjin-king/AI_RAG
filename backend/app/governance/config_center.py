"""场景配置中心（设计书 §2.1 F10 / §6）：知识库 + 检索策略 + Prompt + 权限四要素。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenant import TenantContext
from app.db.models import SceneConfig


async def get_effective_retrieval_config(
    session: AsyncSession, tenant: TenantContext, *,
    knowledge_base_id: Optional[int] = None, scene_id: Optional[str] = None,
) -> dict:
    """合并 默认配置 < KB 配置 < 场景配置（后者覆盖前者）。"""
    cfg = {
        "vector_topk": settings.retrieval_vector_topk,
        "keyword_topk": settings.retrieval_keyword_topk,
        "final_topk": settings.retrieval_final_topk,
        "rrf_k": settings.rrf_k,
        "use_rerank": bool(settings.rerank_api_key and settings.rerank_base_url),
    }
    if knowledge_base_id:
        from app.repositories import knowledge_base as kb_repo

        kb = await kb_repo.get(session, tenant, knowledge_base_id)
        cfg.update(kb.retrieval_config or {})
    if scene_id:
        from app.repositories import governance as gov_repo

        scene = await gov_repo.get_scene(session, tenant, scene_id)
        if scene:
            cfg.update(scene.retrieval_config or {})
    return cfg
