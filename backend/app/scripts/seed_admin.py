"""首次 seed 管理员：python -m app.scripts.seed_admin [--ensure-membership TENANT:ROLE ...]

读取 SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD（默认 admin/changeme，生产务必经环境变量覆盖）。
幂等：管理员已存在则跳过；--ensure-membership 给管理员补第二租户成员身份
（租户不存在则先建；已有该关系则跳过）——E2E 租户切换用例的前置。
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.logging import setup_logging
from app.db.database import session_scope
from app.repositories import users as user_repo


async def main(extra_memberships: list[tuple[str, str]] | None = None) -> None:
    setup_logging()
    async with session_scope() as session:
        created = await user_repo.seed_admin_if_absent(session)
        for tenant_id, role in extra_memberships or []:
            added = await user_repo.ensure_membership(
                session, username=_seed_username(), tenant_id=tenant_id, role=role
            )
            print(f"membership {tenant_id}:{role} {'added' if added else 'exists (skipped)'}")
    print("admin seeded" if created else "admin already exists (skipped)")


def _seed_username() -> str:
    from app.core.config import settings

    return settings.seed_admin_username


def _parse() -> list[tuple[str, str]]:
    ap = argparse.ArgumentParser(description="seed admin user")
    ap.add_argument(
        "--ensure-membership", action="append", default=[], metavar="TENANT:ROLE",
        help="给 seed 管理员补租户成员关系（幂等），如 e2e:admin",
    )
    args = ap.parse_args()
    out: list[tuple[str, str]] = []
    for spec in args.ensure_membership:
        tenant, _, role = spec.partition(":")
        out.append((tenant, role or "admin"))
    return out


if __name__ == "__main__":
    asyncio.run(main(_parse()))
