"""用户 / 租户成员关系仓储（多租户归属）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import TenantModel, User, UserTenantMembership


async def get_user_with_memberships(session, username: str) -> Optional[User]:
    res = await session.execute(
        select(User).options(selectinload(User.memberships)).where(User.username == username)
    )
    return res.scalar_one_or_none()


async def ensure_tenant(session, tenant_id: str, name: Optional[str] = None) -> None:
    res = await session.execute(select(TenantModel).where(TenantModel.tenant_id == tenant_id))
    if res.scalar_one_or_none() is None:
        session.add(TenantModel(tenant_id=tenant_id, name=name or tenant_id))
        await session.flush()


async def create_user(
    session,
    *,
    username: str,
    password: str,
    email: Optional[str] = None,
    is_superadmin: bool = False,
    memberships: Optional[list[tuple[str, str]]] = None,
) -> User:
    """创建用户及其租户成员关系。调用方负责提交。"""
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_superadmin=is_superadmin,
    )
    session.add(user)
    await session.flush()  # 取 user.id
    for tenant_id, role in memberships or []:
        session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant_id, role=role))
    await session.flush()
    return user


async def seed_admin_if_absent(session) -> bool:
    """确保 seed 管理员存在（首次返回 True，已存在返回 False）。幂等。"""
    existing = await get_user_with_memberships(session, settings.seed_admin_username)
    if existing:
        return False
    await ensure_tenant(session, settings.default_tenant_id)
    await create_user(
        session,
        username=settings.seed_admin_username,
        password=settings.seed_admin_password,
        is_superadmin=True,
        memberships=[(settings.default_tenant_id, "admin")],
    )
    return True


async def ensure_membership(
    session, *, username: str, tenant_id: str, role: str = "admin"
) -> bool:
    """给已有用户补一条租户成员关系（租户不存在则先建）。

    E2E 租户切换用例的前置：seed 管理员在第二租户的成员身份。幂等：
    已存在该关系返回 False，新建返回 True。用户不存在时抛 NotFoundError。
    """
    user = await get_user_with_memberships(session, username)
    if user is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"user not found: {username}")
    if any(m.tenant_id == tenant_id for m in user.memberships or []):
        return False
    await ensure_tenant(session, tenant_id)
    session.add(UserTenantMembership(user_id=user.id, tenant_id=tenant_id, role=role))
    await session.flush()
    return True
