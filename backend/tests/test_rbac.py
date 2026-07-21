"""RBAC 前置过滤测试（设计书 §6）。"""
from types import SimpleNamespace

import pytest

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.governance.authz import PermissionFilter, PermissionResolver
from app.services.retrieval import orchestrator


def test_permission_filter_allows_doc():
    open_p = PermissionFilter()
    assert open_p.allows_doc(123) is True
    allowlist = PermissionFilter(doc_ids={1, 2})
    assert allowlist.allows_doc(1) and not allowlist.allows_doc(9)
    deny = PermissionFilter(denied_doc_ids={5})
    assert deny.allows_doc(4) and not deny.allows_doc(5)


@pytest.mark.asyncio
async def test_resolver_default_permissive(monkeypatch):
    monkeypatch.setattr("app.governance.authz.settings.rbac_enabled", True)
    monkeypatch.setattr("app.governance.authz.settings.rbac_policy", "")
    r = PermissionResolver()
    pf = await r.resolve(TenantContext("A"))
    assert not pf.restricted  # 无规则 → 宽放


@pytest.mark.asyncio
async def test_resolver_scene_rules_restrict(monkeypatch):
    monkeypatch.setattr("app.governance.authz.settings.rbac_enabled", True)
    monkeypatch.setattr("app.governance.authz.settings.rbac_policy", "")
    scene = SimpleNamespace(permission_rules={"allowed_doc_ids": [10, 11], "denied_doc_ids": [99]})
    r = PermissionResolver()
    pf = await r.resolve(TenantContext("A"), scene=scene)
    assert pf.doc_ids == {10, 11}
    assert pf.denied_doc_ids == {99}
    assert pf.allows_doc(10) and not pf.allows_doc(12) and not pf.allows_doc(99)


@pytest.mark.asyncio
async def test_orchestrator_permission_prefilter(sqlite_session):
    """权限前置过滤：PermissionFilter(doc_ids={A}) 时，B 文档的 chunk 不得被召回。"""
    s = sqlite_session
    dA = Document(tenant_id="A", title="A", object_key="a", content_type="text/plain", status="indexed")
    dB = Document(tenant_id="A", title="B", object_key="b", content_type="text/plain", status="indexed")
    s.add_all([dA, dB])
    await s.flush()
    s.add(Chunk(tenant_id="A", document_id=dA.id, ordinal=0, content="alpha beta common term"))
    s.add(Chunk(tenant_id="A", document_id=dB.id, ordinal=0, content="alpha beta common term"))
    await s.commit()

    # 仅允许 doc A
    res = await orchestrator.retrieve(
        s, TenantContext("A"), "alpha",
        permission=PermissionFilter(doc_ids={dA.id}),
    )
    assert res.chunks
    assert all(c.doc_id == dA.id for c in res.chunks), "B 文档不得越权返回"

    # 拒绝 doc A → 只剩 B
    res2 = await orchestrator.retrieve(
        s, TenantContext("A"), "alpha",
        permission=PermissionFilter(denied_doc_ids={dA.id}),
    )
    assert res2.chunks and all(c.doc_id == dB.id for c in res2.chunks)
