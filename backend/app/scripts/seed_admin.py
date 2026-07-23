"""首次 seed 管理员：python -m app.scripts.seed_admin

读取 SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD（默认 admin/changeme，生产务必经环境变量覆盖）。
幂等：管理员已存在则跳过。需 infra（PG）已就绪。
"""
from __future__ import annotations

import asyncio

from app.core.logging import setup_logging
from app.db.database import session_scope
from app.repositories import users as user_repo


async def main() -> None:
    setup_logging()
    async with session_scope() as session:
        created = await user_repo.seed_admin_if_absent(session)
    print("admin seeded" if created else "admin already exists (skipped)")


if __name__ == "__main__":
    asyncio.run(main())
