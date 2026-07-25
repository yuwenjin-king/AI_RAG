"""端到端 RAG 编排（设计书 §4.4 × §4.5）。

对话问答：检索编排 → 上下文构建 → LLM 流式生成 → 引用标注 → 落库。
为避免长连接占用 DB，DB 操作拆成多个短 session。
"""
from __future__ import annotations

import time
from typing import AsyncIterator, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import CHAT_LATENCY, LLM_CALLS, RAG_REQUESTS
from app.core.tenant import TenantContext
from app.db.database import session_scope
from app.db.models import Role
from app.repositories import conversation as conv_repo
from app.schemas.chat import ChatRequest, Citation, RetrieveResponse
from app.services.generation import citation as citation_svc
from app.services.generation import llm_gateway, prompts
from app.services.generation.llm_gateway import get_llm
from app.services.retrieval import orchestrator

log = get_logger(__name__)


def _evt(event: str, data) -> dict:
    return {"event": event, "data": data}


async def chat_stream(
    tenant: TenantContext, req: ChatRequest, *, role: Optional[str] = None
) -> AsyncIterator[dict]:
    """流式问答，产出 SSE 事件 dict 序列。"""
    start = time.perf_counter()
    RAG_REQUESTS.labels(tenant=tenant.tenant_id).inc()
    # 1) 取/建会话 + 历史 + 场景 + A/B 变体（短 session）
    async with session_scope() as session:
        conv = await conv_repo.get_or_create(
            session, tenant,
            conversation_id=req.conversation_id,
            knowledge_base_id=req.knowledge_base_id,
        )
        conv_id = conv.id
        history = await conv_repo.history(session, tenant, conv_id, limit=8)
        scene = None
        if req.scene_id:
            from app.repositories import governance as gov_repo
            scene = await gov_repo.get_scene(session, tenant, req.scene_id)
    history_msgs = [{"role": m.role, "content": m.content} for m in history]

    # A/B 变体（设计书 §9）：按 用户×场景 确定性分桶；变体可覆盖检索参数
    variant = None
    variant_name = None
    if scene is not None:
        from app.eval.ab import pick_variant, variant_key
        variant = pick_variant(scene, variant_key(tenant.tenant_id, req.scene_id, str(conv_id)))
        variant_name = variant.get("name") if variant else None
    yield _evt("meta", {"conversation_id": conv_id, "tenant_id": tenant.tenant_id, "variant": variant_name})

    # 2) 检索（短 session）
    effective_top_k = req.top_k
    if variant and isinstance(variant.get("retrieval_config"), dict):
        vk = variant["retrieval_config"].get("final_topk")
        if vk:
            effective_top_k = int(vk)
    agentic_meta = None
    async with session_scope() as session:
        # RBAC：解析权限并作为检索前置过滤（设计书 §6）
        from app.governance.authz import get_resolver
        permission = await get_resolver().resolve(tenant, role=role, scene=scene)
        if settings.agentic_enabled:
            # Agentic RAG（plan_three §2）：充分性评估 + 迭代召回
            from app.services.retrieval import agentic as agentic_mod
            aresult = await agentic_mod.agentic_retrieve(
                session, tenant, req.query,
                knowledge_base_id=req.knowledge_base_id, top_k=effective_top_k,
                scene=scene, history=history_msgs, permission=permission,
            )
            chunks = aresult.chunks
            degraded: List[str] = list(aresult.degraded)
            agentic_meta = {
                "iterations": aresult.iterations,
                "sufficiency": aresult.sufficiency_score,
                "followups": aresult.followups_used,
            }
        else:
            result = await orchestrator.retrieve(
                session, tenant, req.query,
                knowledge_base_id=req.knowledge_base_id,
                top_k=effective_top_k, scene=scene, history=history_msgs, permission=permission,
            )
            chunks = result.chunks
            degraded: List[str] = list(result.degraded)

    # 3) 引用标注（先发，供前端即时展示）
    citations: List[Citation] = citation_svc.build_citations(chunks)
    yield _evt(
        "citations",
        [c.model_dump(mode="json") for c in citations],
    )

    # 4) 流式生成
    messages = prompts.build_messages(req.query, chunks, history=history_msgs)
    llm = get_llm(chunks=chunks)
    if llm.is_mock:
        degraded.append("llm.mock")

    answer_parts: List[str] = []
    model_label = "mock" if llm.is_mock else settings.llm_model
    try:
        async for token in llm.stream(messages):
            answer_parts.append(token)
            yield _evt("token", {"text": token})
        LLM_CALLS.labels(model=model_label, status="mock" if llm.is_mock else "ok").inc()
    except Exception as e:  # noqa: BLE001
        log.error("rag.stream.failed err=%s", e)
        degraded.append("llm.stream_failed")
        LLM_CALLS.labels(model=model_label, status="failed").inc()
        fallback = "（生成失败，已降级。请检查 LLM 配置。）"
        answer_parts.append(fallback)
        yield _evt("token", {"text": fallback})

    answer = "".join(answer_parts).strip()

    # 答案自检（Agentic 开启 + 真实 LLM 时）：faithfulness 校验，失败则降级声明
    selfcheck_meta = None
    if settings.agentic_enabled and settings.agentic_selfcheck_enabled and not llm.is_mock:
        try:
            from app.services.generation import selfcheck as selfcheck_mod
            sc = await selfcheck_mod.check_faithfulness(answer, chunks)
            selfcheck_meta = {"pass": sc.passed, "score": sc.score, "reason": sc.reason}
            if not sc.passed:
                degraded.append("agentic.selfcheck_failed")
                from app.core.metrics import SELFCHECK_FAIL
                SELFCHECK_FAIL.inc()
                note = "\n\n（自检提示：本回答的证据支撑较弱，请核实。）"
                yield _evt("token", {"text": note})
                answer = (answer + note).strip()
        except Exception as e:  # noqa: BLE001
            log.warning("rag.selfcheck.failed err=%s", e)

    # 成本估算：流式无 usage，按字符近似计 token（仅真实 LLM）
    if not llm.is_mock:
        from app.core.metrics import LLM_TOKENS

        prompt_est = sum(len(m.get("content", "")) for m in messages) // 4
        LLM_TOKENS.labels(model=model_label, direction="prompt").inc(max(1, prompt_est))
        LLM_TOKENS.labels(model=model_label, direction="completion").inc(max(1, len(answer) // 4))

    # 5) 落库（短 session）
    try:
        async with session_scope() as session:
            await conv_repo.add_message(
                session, tenant, conv_id, role=Role.USER, content=req.query
            )
            await conv_repo.add_message(
                session, tenant, conv_id, role=Role.ASSISTANT, content=answer,
                citations=[c.model_dump(mode="json") for c in citations],
                degraded=degraded, meta={"variant": variant_name} if variant_name else {},
            )
    except Exception as e:  # noqa: BLE001
        log.warning("rag.persist.failed err=%s", e)

    CHAT_LATENCY.labels(tenant=tenant.tenant_id).observe(time.perf_counter() - start)
    done_data: dict = {"conversation_id": conv_id, "answer": answer, "degraded": sorted(set(degraded))}
    if agentic_meta is not None:
        done_data["agentic"] = agentic_meta
    if selfcheck_meta is not None:
        done_data["selfcheck"] = selfcheck_meta
    yield _evt("done", done_data)


async def retrieve_only(
    tenant: TenantContext, req: ChatRequest, *, role: Optional[str] = None
):
    """纯检索（检索与生成解耦：/retrieve 复用）。"""
    async with session_scope() as session:
        scene = None
        if req.scene_id:
            from app.repositories import governance as gov_repo
            scene = await gov_repo.get_scene(session, tenant, req.scene_id)
        from app.governance.authz import get_resolver
        permission = await get_resolver().resolve(tenant, role=role, scene=scene)
        if settings.agentic_enabled:
            from app.services.retrieval import agentic as agentic_mod
            a = await agentic_mod.agentic_retrieve(
                session, tenant, req.query,
                knowledge_base_id=req.knowledge_base_id, top_k=req.top_k,
                scene=scene, permission=permission,
            )
            return RetrieveResponse(query=req.query, chunks=a.chunks, degraded=a.degraded)
        return await orchestrator.retrieve(
            session, tenant, req.query,
            knowledge_base_id=req.knowledge_base_id,
            top_k=req.top_k, scene=scene, permission=permission,
        )
