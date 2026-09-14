"""治理仓储：模型配置 / 场景配置 / 反馈 / 审计日志。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.db.models import Feedback, ModelConfig, OperationLog, SceneConfig


# ---- 模型配置 ----
async def upsert_model_config(
    session: AsyncSession, tenant: TenantContext, *, kind: str, name: str,
    provider: str = "openai_compatible", model: str, base_url: Optional[str] = None,
    api_key_ref: Optional[str] = None, params: Optional[dict] = None, is_default: bool = False,
) -> ModelConfig:
    obj = (
        await session.execute(
            select(ModelConfig).where(
                ModelConfig.tenant_id == tenant.tenant_id,
                ModelConfig.kind == kind,
                ModelConfig.name == name,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        obj = ModelConfig(
            tenant_id=tenant.tenant_id, kind=kind, name=name, provider=provider, model=model,
            base_url=base_url, api_key_ref=api_key_ref, params=params or {}, is_default=is_default,
        )
        session.add(obj)
    else:
        obj.provider, obj.model, obj.base_url, obj.api_key_ref = provider, model, base_url, api_key_ref
        obj.params = params or {}
        obj.is_default = is_default
    await session.flush()
    return obj


async def default_model(
    session: AsyncSession, tenant: TenantContext, kind: str
) -> Optional[ModelConfig]:
    return (
        await session.execute(
            select(ModelConfig)
            .where(
                ModelConfig.tenant_id == tenant.tenant_id,
                ModelConfig.kind == kind,
                ModelConfig.is_default.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


# ---- 场景配置 ----
async def get_scene(
    session: AsyncSession, tenant: TenantContext, scene_id: str
) -> Optional[SceneConfig]:
    return (
        await session.execute(
            select(SceneConfig).where(
                SceneConfig.tenant_id == tenant.tenant_id,
                SceneConfig.scene_id == scene_id,
                SceneConfig.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def upsert_scene(session: AsyncSession, tenant: TenantContext, **fields) -> SceneConfig:
    obj = await get_scene(session, tenant, fields["scene_id"])
    if obj is None:
        obj = SceneConfig(tenant_id=tenant.tenant_id, **fields)
        session.add(obj)
    else:
        for k, v in fields.items():
            setattr(obj, k, v)
    await session.flush()
    return obj


# ---- 反馈 ----
async def add_feedback(
    session: AsyncSession, tenant: TenantContext, *, message_id: Optional[int],
    rating: Optional[int], comment: Optional[str],
) -> Feedback:
    obj = Feedback(
        tenant_id=tenant.tenant_id, message_id=message_id, rating=rating, comment=comment,
    )
    session.add(obj)
    await session.flush()
    return obj


# ---- 审计 ----
async def log(
    session: AsyncSession, tenant: TenantContext, *, action: str,
    target: Optional[str] = None, actor: Optional[str] = None, detail: Optional[dict] = None,
) -> None:
    session.add(
        OperationLog(
            tenant_id=tenant.tenant_id, action=action, target=target, actor=actor,
            detail=detail or {},
        )
    )
    await session.flush()


def _naive_utc(v: datetime) -> datetime:
    """比较参数统一 naive-UTC：sqlite 无时区（回读 naive），PG 容器 TZ=UTC 下等价。
    混比 aware/naive 会触发 ORM in-Python 求值器 TypeError。"""
    return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo is not None else v


async def list_audit(
    session: AsyncSession, tenant: TenantContext, *, action: Optional[str] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None, limit: int = 200,
) -> list[OperationLog]:
    stmt = select(OperationLog).where(OperationLog.tenant_id == tenant.tenant_id)
    if action:
        stmt = stmt.where(OperationLog.action == action)
    if since is not None:  # 保留期审计窗口查询（plan_four §1.4）
        stmt = stmt.where(OperationLog.created_at >= _naive_utc(since))
    if until is not None:
        stmt = stmt.where(OperationLog.created_at < _naive_utc(until))
    return list(
        (
            await session.execute(stmt.order_by(OperationLog.id.desc()).limit(limit))
        ).scalars().all()
    )


async def purge_expired(
    session: AsyncSession, *, retention_days: Optional[int] = None
) -> int:
    """删除超过保留期的审计日志，返回删除行数。跨租户（合规保留期是全局策略）。"""
    days = settings.audit_retention_days if retention_days is None else retention_days
    cutoff = _naive_utc(datetime.now(timezone.utc) - timedelta(days=days))
    res = await session.execute(delete(OperationLog).where(OperationLog.created_at < cutoff))
    return int(res.rowcount or 0)
