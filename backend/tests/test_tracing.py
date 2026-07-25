"""OTel 追踪测试（plan_three §3）。

- test_span_noop_when_unavailable：本地无 opentelemetry 也跑——证明带 span 的业务代码不报错。
- 其余用 importorskip：本地无 OTel 自动跳过，Docker/CI（装了 otel）执行，断言 span 生成/属性/嵌套。
"""
from __future__ import annotations

import pytest

from app.core import tracing as tracing_mod
from app.core.tenant import TenantContext
from app.schemas.chat import RetrievedChunk, RetrieveResponse
from app.services.retrieval import agentic, orchestrator

Tenant = TenantContext(tenant_id="acme")


def test_span_noop_when_unavailable():
    """无 OTel/未启用 → span() no-op。本地无 otel 时这条仍执行。"""
    was_available = tracing_mod._available
    was_tracer = tracing_mod._tracer
    tracing_mod._available = False
    tracing_mod._tracer = None
    try:
        with tracing_mod.span("noop", k=1, tenant="acme") as s:
            assert s is None  # 降级：不产生 span，但代码块正常执行
    finally:
        tracing_mod._available = was_available
        tracing_mod._tracer = was_tracer


@pytest.fixture
def otel_exporter(monkeypatch):
    """装了 opentelemetry-sdk 才执行；否则使用此 fixture 的测试被跳过。"""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import InMemorySpanExporter, SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(tracing_mod, "_tracer", tracer)
    monkeypatch.setattr(tracing_mod, "_available", True)
    yield exporter
    provider.shutdown()


def test_span_records_attributes_and_nesting(otel_exporter):
    with tracing_mod.span("parent", attr1="x", tenant="acme"):
        with tracing_mod.span("child", num=5):
            pass
    spans = otel_exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "parent" in names and "child" in names
    parent = next(s for s in spans if s.name == "parent")
    child = next(s for s in spans if s.name == "child")
    assert parent.attributes.get("attr1") == "x"
    assert child.attributes.get("num") == 5
    # 嵌套：child 的 parent 应为 parent
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id


async def test_agentic_produces_assess_span(otel_exporter, monkeypatch):
    """agentic_retrieve 产生 agentic.assess span 并带 iteration 属性。"""
    monkeypatch.setattr(agentic.settings, "llm_api_key", "")  # 走启发式

    async def fake(session, tenant, query, *, knowledge_base_id=None, top_k=None,
                   scene=None, history=None, permission=None):
        return RetrieveResponse(query=query, chunks=[
            RetrievedChunk(chunk_id=1, doc_id=1, content="apple banana fruit", score=0.9, source="fused"),
            RetrievedChunk(chunk_id=2, doc_id=1, content="apple red", score=0.8, source="fused"),
            RetrievedChunk(chunk_id=3, doc_id=1, content="banana yellow", score=0.7, source="fused"),
        ], degraded=[])

    monkeypatch.setattr(orchestrator, "retrieve", fake)
    await agentic.agentic_retrieve(None, Tenant, "apple banana", max_iterations=2)

    spans = otel_exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert "agentic.assess" in names
    assess = next(s for s in spans if s.name == "agentic.assess")
    assert "iteration" in assess.attributes  # 业务属性已记录
