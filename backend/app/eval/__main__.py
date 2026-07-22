"""评估 CLI：python -m app.eval --tenant default --scene <scene_id> [--top-k N]"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.core.logging import setup_logging
from app.core.tenant import TenantContext
from app.db.database import dispose_engine, session_scope
from app.eval.runner import run_eval


async def _run() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.eval")
    ap.add_argument("--tenant", required=True, help="租户 ID")
    ap.add_argument("--scene", required=True, help="场景 ID（评估集归属）")
    ap.add_argument("--top-k", type=int, default=None, help="检索 Top-K（默认取配置）")
    args = ap.parse_args()

    setup_logging()
    async with session_scope() as session:
        report = await run_eval(session, TenantContext(args.tenant), args.scene, top_k=args.top_k)
    await dispose_engine()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_run())
