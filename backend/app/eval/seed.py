"""评估语料装载器（plan_four §2）。

把 `corpus.py` 的确定性语料 seed 入库：建 KB + 场景 + 文档 + chunk + 评估用例。
- 离线：sqlite，直接 seed chunk（BM25 本地兜底即可跑 run_eval 回归门禁）。
- 真实环境（plan_four §3）：seed 后由 OpenSearch/Milvus 索引；或改走 API 上传走全量 ingest。

幂等：reset=False 且场景已有用例 → 直接返回（防重复）；reset=True → 清场景用例 +
语料文档后重建。文档以稳定 checksum 去重（UniqueConstraint tenant+checksum）。

CLI：`python -m app.eval.seed --tenant default --scene eval [--reset]`
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, setup_logging
from app.core.tenant import TenantContext
from app.db.database import dispose_engine, session_scope
from app.db.models import Chunk, Document, EvalCase, KnowledgeBase
from app.eval import corpus as C
from app.eval.corpus import KB_NAME_DEFAULT, SCENE_ID_DEFAULT
from app.repositories import eval as eval_repo
from app.repositories import governance as gov_repo

log = get_logger(__name__)

_EVAL_FLAG = {"eval_corpus": True}


async def _get_or_create_kb(session: AsyncSession, tenant: TenantContext, name: str) -> KnowledgeBase:
    obj = (
        await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == tenant.tenant_id, KnowledgeBase.name == name
            )
        )
    ).scalar_one_or_none()
    if obj is not None:
        return obj
    kb = KnowledgeBase(tenant_id=tenant.tenant_id, name=name, description="离线评估语料知识库")
    session.add(kb)
    await session.flush()
    return kb


async def _clear_corpus(session: AsyncSession, tenant: TenantContext, scene_id: str) -> None:
    """清空该场景的评估用例 + 所有语料文档（及其 chunk，cascade）。"""
    await session.execute(
        delete(EvalCase).where(EvalCase.tenant_id == tenant.tenant_id, EvalCase.scene_id == scene_id)
    )
    await session.execute(
        delete(Document).where(Document.tenant_id == tenant.tenant_id, Document.meta.contains(_EVAL_FLAG))
    )
    await session.flush()


async def seed_eval_corpus(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    scene_id: str = SCENE_ID_DEFAULT,
    kb_name: str = KB_NAME_DEFAULT,
    reset: bool = False,
) -> dict:
    """装载评估语料；返回 {scene_id, kb_id, doc_map(slug->id), n_docs, n_cases}。"""
    # 幂等：未要求 reset 且场景已有用例 → 视为已装载
    existing = await eval_repo.list_cases(session, tenant, scene_id, limit=1)
    if existing and not reset:
        log.info("eval.seed.already_seeded scene=%s tenant=%s", scene_id, tenant.tenant_id)
        return {"scene_id": scene_id, "tenant": tenant.tenant_id, "skipped": True}

    if reset:
        await _clear_corpus(session, tenant, scene_id)

    kb = await _get_or_create_kb(session, tenant, kb_name)
    # 场景绑定 KB（run_eval 取 scene.knowledge_base_ids[0] 作检索范围）
    await gov_repo.upsert_scene(
        session, tenant,
        scene_id=scene_id, name="评估场景",
        knowledge_base_ids=[kb.id], is_active=True,
    )

    # 文档 + chunk（每 passage 一 chunk，保留 page_no/bbox）
    slug2id: dict[str, int] = {}
    for doc in C.CORPUS_DOCS:
        checksum = f"eval-{doc.slug}"
        existing_doc = (
            await session.execute(
                select(Document).where(
                    Document.tenant_id == tenant.tenant_id, Document.checksum == checksum
                )
            )
        ).scalar_one_or_none()
        if existing_doc is None:
            orm_doc = Document(
                tenant_id=tenant.tenant_id,
                knowledge_base_id=kb.id,
                title=doc.title,
                object_key=f"eval/{doc.slug}.txt",
                content_type="text/plain",
                status="indexed",
                checksum=checksum,
                meta={**_EVAL_FLAG, "slug": doc.slug},
            )
            session.add(orm_doc)
            await session.flush()
            orm = orm_doc
        else:
            # 已存在 → 清旧 chunk 重建（保证与语料一致）
            await session.execute(delete(Chunk).where(Chunk.document_id == existing_doc.id))
            await session.flush()
            orm = existing_doc
        slug2id[doc.slug] = orm.id
        for ordinal, p in enumerate(doc.passages):
            session.add(
                Chunk(
                    tenant_id=tenant.tenant_id,
                    document_id=orm.id,
                    ordinal=ordinal,
                    content=p.text,
                    page_no=p.page_no,
                    bbox=p.bbox,
                    extra={"kind": "text", "eval_corpus": True},
                )
            )
    await session.flush()

    # 评估用例（slug → doc_id）
    n_cases = 0
    for case in C.EVAL_CASES:
        expected_doc_ids = [slug2id[s] for s in case.expected_docs if s in slug2id]
        await eval_repo.add_case(
            session, tenant,
            scene_id=scene_id, query=case.query,
            expected_answer=case.gold_answer,
            expected_doc_ids=expected_doc_ids,
            expected_page=case.expected_page,
            expected_bbox=case.expected_bbox,
            tags=list(case.tags),
            meta={"slug": case.slug},
        )
        n_cases += 1

    await session.commit()
    log.info(
        "eval.seed.done scene=%s tenant=%s docs=%s cases=%s",
        scene_id, tenant.tenant_id, len(slug2id), n_cases,
    )
    return {
        "scene_id": scene_id,
        "tenant": tenant.tenant_id,
        "kb_id": kb.id,
        "doc_map": slug2id,
        "n_docs": len(slug2id),
        "n_cases": n_cases,
    }


async def _run() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.eval.seed")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--scene", default=SCENE_ID_DEFAULT)
    ap.add_argument("--reset", action="store_true", help="清空该场景用例 + 语料文档后重建")
    args = ap.parse_args()

    setup_logging()
    async with session_scope() as session:
        result = await seed_eval_corpus(
            session, TenantContext(args.tenant), scene_id=args.scene, reset=args.reset
        )
    await dispose_engine()
    print(f"seeded: {result}")


if __name__ == "__main__":
    asyncio.run(_run())
