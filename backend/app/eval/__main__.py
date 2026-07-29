"""评估 CLI：python -m app.eval --tenant default --scene <scene_id> [--top-k N] [--with-generation]"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.tenant import TenantContext
from app.db.database import dispose_engine, session_scope
from app.eval.runner import GenerateFn, run_eval
from app.schemas.chat import RetrievedChunk


def _make_llm_generate() -> Optional[GenerateFn]:
    """构造基于 LLM 网关的 generate 回调（--with-generation 时用）。无 key → None（mock 模板）。"""
    from app.services.generation.llm_gateway import get_llm

    async def generate(query: str, context: str, chunks: List[RetrievedChunk]) -> str:
        llm = get_llm(chunks)
        messages = [
            {"role": "system", "content": "根据下方检索到的上下文简明回答问题；上下文不足以回答时直说不知道。"},
            {"role": "user", "content": f"上下文:\n{context}\n\n问题: {query}"},
        ]
        return await llm.complete(messages)

    return generate


async def _run() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.eval")
    ap.add_argument("--tenant", required=True, help="租户 ID")
    ap.add_argument("--scene", required=True, help="场景 ID（评估集归属）")
    ap.add_argument("--top-k", type=int, default=None, help="检索 Top-K（默认取配置）")
    ap.add_argument(
        "--with-generation", action="store_true",
        help="额外跑生成层指标（faithfulness / answer_overlap）。无 LLM key 时为 mock 模板，仅证链路。",
    )
    args = ap.parse_args()

    generate = None
    if args.with_generation:
        generate = _make_llm_generate()
        if not settings.llm_api_key:
            print("注意：未配置 LLM_API_KEY，--with-generation 将走 mock 模板答案（faithfulness 仅证链路，非真实质量）。")

    setup_logging()
    async with session_scope() as session:
        report = await run_eval(
            session, TenantContext(args.tenant), args.scene,
            top_k=args.top_k, generate=generate,
        )
    await dispose_engine()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_run())
