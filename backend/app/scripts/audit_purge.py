"""手动清除超期审计日志：python -m app.scripts.audit_purge [--days N]

保留期默认取 settings.audit_retention_days（90 天）。worker 启动时也会自动清扫一次；
本脚本供运维按需执行（清完打印删除行数）。幂等：无超期行时删除 0 行。
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.logging import setup_logging
from app.db.database import session_scope
from app.governance.audit import purge_expired


async def _run(days: int | None) -> None:
    setup_logging()
    async with session_scope() as session:
        n = await purge_expired(session, retention_days=days)
    print(f"audit purged rows={n}")


def main() -> None:
    ap = argparse.ArgumentParser(description="purge expired audit logs")
    ap.add_argument("--days", type=int, default=None, help="覆盖保留期（默认取配置）")
    args = ap.parse_args()
    asyncio.run(_run(args.days))


if __name__ == "__main__":
    main()
