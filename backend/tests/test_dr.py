"""DR 备份恢复测试（plan_three §6）。

覆盖：
- manifest 纯逻辑（sha256 / 往返 / 校验缺失+篡改 / 可恢复性）
- PG 行级 dump/restore 在 sqlite 上无损往返（datetime + JSONB + 显式主键）
- infra 导出/导入在不可用时优雅降级（不触真实 Milvus/OS/MinIO）
- backup/restore 编排（monkeypatched stores + 真 PG 路径 + 保留清理 + 篡改拒绝）
"""
from __future__ import annotations

import io
import json
import tarfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db import models  # noqa: F401  注册所有表
from app.db.models import (
    Chunk,
    Document,
    KnowledgeBase,
    TenantModel,
    User,
    UserTenantMembership,
)
from app.infra import milvus_store, object_storage, opensearch_store
from app.scripts.dr import backup as backup_mod
from app.scripts.dr import manifest as M
from app.scripts.dr import pg_meta, restore as restore_mod, stores


# ===== helpers =====
def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    Path(path).write_bytes(buf.getvalue())


def _make_scope(Session):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def _scope():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _scope


async def _build_seeded_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(TenantModel(id=1, tenant_id="default", name="Default", settings={"region": "cn"}))
        s.add(User(id=1, username="alice", password_hash="pbkdf2$h", email="a@x"))
        s.add(UserTenantMembership(id=1, user_id=1, tenant_id="default", role="admin"))
        s.add(KnowledgeBase(id=1, tenant_id="default", name="KB1"))
        s.add(Document(id=1, tenant_id="default", knowledge_base_id=1, title="Doc", object_key="t/d.pdf", checksum="abc"))
        s.add(Chunk(id=1, tenant_id="default", document_id=1, content="hello", vector_id="vec-1", bbox=[0.1, 0.2, 0.3, 0.4]))
        await s.commit()
    return engine, Session


# fakes（async 对应 milvus/opensearch，sync 对应 minio）
async def _fake_export_milvus(path):
    _write_tar(path, {"rag_chunks.jsonl": b'{"vector_id":"v1","embedding":[0.1]}\n'})
    return 1, {"collections": {"rag_chunks": 1}}


def _fake_export_minio(path):
    _write_tar(path, {"docs/a.pdf": b"%PDF-1.4"})
    return 1, {"objects": 1}


async def _fake_export_opensearch(path):
    _write_tar(path, {"rag-chunks-default.jsonl": b'{"chunk_id":1}\n'})
    return 1, {"indexes": {"rag-chunks-default": 1}}


async def _fake_import_milvus(_path):
    return 1, {"collections": {"rag_chunks": {"restored": 1, "expected": 1}}}


def _fake_import_minio(_path):
    return 1, {"objects": 1}


async def _fake_import_opensearch(_path):
    return 1, {"indexes": {"rag-chunks-default": {"restored": 1, "expected": 1}}}


def _enable_all_infra(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(milvus_store, "is_available", lambda: True)
    monkeypatch.setattr(object_storage, "is_available", lambda: True)
    monkeypatch.setattr(opensearch_store, "is_available", lambda: True)


# ===== manifest 纯逻辑 =====
def test_sha256_bytes():
    assert M.sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_make_artifact_and_verify(tmp_path):
    f = tmp_path / "pg.json"
    f.write_bytes(b"data")
    a = M.make_artifact("postgres", f, tmp_path, 3, {"tenants": 1})
    assert a.store == "postgres" and a.path == "pg.json"
    assert a.sha256 == M.sha256_bytes(b"data")
    assert a.size_bytes == 4 and a.count == 3 and a.detail == {"tenants": 1}

    man = M.BackupManifest(backup_id="b1", created_at="t", software_version="0.1.0", stores=[a])
    M.write_manifest(man, tmp_path)
    back = M.read_manifest(tmp_path)
    assert back.stores[0].sha256 == a.sha256

    report = M.verify_manifest(back, tmp_path)
    assert report.passed and report.ok == ["postgres"] and report.recoverable


def test_verify_detects_missing_and_mismatch(tmp_path):
    pg = tmp_path / "pg.json"
    pg.write_bytes(b"orig")
    a_pg = M.make_artifact("postgres", pg, tmp_path, 1)
    a_milvus = M.StoreArtifact(store="milvus", path="milvus.tar", sha256="0" * 64, size_bytes=1, count=0)
    man = M.BackupManifest(backup_id="b", created_at="t", software_version="0.1.0", stores=[a_pg, a_milvus])

    report = M.verify_manifest(man, tmp_path)
    assert report.ok == ["postgres"] and report.missing == ["milvus"]  # milvus.tar 未创建

    pg.write_bytes(b"tampered")  # 篡改 → sha256 不匹配
    report2 = M.verify_manifest(man, tmp_path)
    assert report2.mismatched == ["postgres"] and not report2.passed


def test_recoverable_requires_complete_postgres():
    man = M.BackupManifest(backup_id="b", created_at="t", software_version="0.1.0", stores=[])
    assert not man.is_recoverable()
    pg = M.StoreArtifact(store="postgres", path="pg.json", sha256="x", size_bytes=1, count=0, status=M.STATUS_COMPLETE)
    man.stores.append(pg)
    assert man.is_recoverable()
    pg.status = M.STATUS_PARTIAL
    assert not man.is_recoverable()


def test_serialize_roundtrip():
    man = M.BackupManifest(
        backup_id="b1", created_at="2026-01-01T00:00:00Z", software_version="0.1.0",
        status=M.STATUS_PARTIAL, notes=["degraded"], rpo_target_seconds=3600,
    )
    man.stores.append(M.StoreArtifact(store="minio", path="minio.tar", sha256="a" * 64, size_bytes=10, count=2))
    back = M.deserialize(M.serialize(man))
    assert back.backup_id == "b1" and back.status == M.STATUS_PARTIAL
    assert back.stores[0].store == "minio" and back.notes == ["degraded"] and back.rpo_target_seconds == 3600


# ===== PG 行级 dump/restore（sqlite 往返） =====
async def test_pg_meta_roundtrip(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        s.add(TenantModel(id=7, tenant_id="acme", name="Acme", settings={"region": "cn", "n": 3}))
        s.add(User(id=2, username="bob", password_hash="h$2", email="b@x"))
        s.add(UserTenantMembership(id=9, user_id=2, tenant_id="acme", role="viewer"))
        await s.commit()

    async with Session() as s:
        data = await pg_meta.dump_metadata(s)
    p = tmp_path / "pg.json"
    assert pg_meta.write_metadata(data, p) == 3

    # 全新库回灌
    engine2 = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True)
    async with engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session2 = async_sessionmaker(bind=engine2, expire_on_commit=False)
    async with Session2() as s:
        n = await pg_meta.restore_metadata(s, pg_meta.read_metadata(p))
        await s.commit()
    assert n == 3

    async with Session2() as s:
        t = (await s.execute(TenantModel.__table__.select())).mappings().first()
        assert t["id"] == 7 and t["tenant_id"] == "acme"  # 显式主键保留
        assert t["settings"] == {"region": "cn", "n": 3}   # JSONB 往返
        assert t["created_at"] is not None                 # datetime 往返
        m = (await s.execute(UserTenantMembership.__table__.select())).mappings().first()
        assert m["role"] == "viewer" and m["user_id"] == 2  # FK 关系保留
        u = (await s.execute(User.__table__.select())).mappings().first()
        assert u["username"] == "bob" and u["email"] == "b@x"

    await engine.dispose()
    await engine2.dispose()


# ===== infra 不可用降级（不触真实 infra） =====
async def test_milvus_helpers_degrade_when_unavailable():
    assert await milvus_store.list_rag_collections() == []
    assert await milvus_store.export_collection("rag_chunks") == []
    assert await milvus_store.import_collection("rag_chunks", [{"x": 1}]) == 0


async def test_opensearch_helpers_degrade_when_unavailable():
    assert await opensearch_store.list_rag_indexes() == []
    assert await opensearch_store.export_index("rag-chunks-default") == []


def test_object_storage_list_degrades_when_unavailable():
    assert object_storage.list_object_keys() == []


# ===== 编排：backup =====
async def test_backup_creates_full_manifest(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    _enable_all_infra(monkeypatch)
    monkeypatch.setattr(stores, "export_milvus", _fake_export_milvus)
    monkeypatch.setattr(stores, "export_minio", _fake_export_minio)
    monkeypatch.setattr(stores, "export_opensearch", _fake_export_opensearch)

    man = await backup_mod.backup(out_root=tmp_path, backup_id="bk1")
    bdir = tmp_path / "bk1"
    assert man.status == M.STATUS_COMPLETE
    assert [a.store for a in man.stores] == ["postgres", "milvus", "minio", "opensearch"]
    assert man.store("postgres").count >= 6
    assert M.verify_manifest(man, bdir).passed
    assert (bdir / "manifest.json").exists()
    await engine.dispose()


async def test_backup_partial_when_infra_down(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    # is_available 保持默认 False
    man = await backup_mod.backup(out_root=tmp_path, backup_id="bk2")
    assert man.status == M.STATUS_PARTIAL
    assert man.store("postgres") is not None
    assert [a.store for a in man.stores] == ["postgres"]
    assert any("unavailable" in n for n in man.notes)
    assert M.verify_manifest(man, tmp_path / "bk2").passed  # 仅 pg，仍自洽
    await engine.dispose()


async def test_backup_prunes_beyond_retention(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    monkeypatch.setattr(backup_mod.settings, "backup_retention", 2)
    for i in range(3):
        await backup_mod.backup(out_root=tmp_path, backup_id=f"bk{i}")
    dirs = sorted(d.name for d in tmp_path.glob("*/"))
    assert dirs == ["bk1", "bk2"]  # bk0（最旧）被清理
    await engine.dispose()


# ===== 编排：restore =====
async def test_restore_pg_roundtrip_infra_down(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    await backup_mod.backup(out_root=tmp_path, backup_id="bk")
    bdir = tmp_path / "bk"
    await engine.dispose()

    engine2 = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True)
    async with engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session2 = async_sessionmaker(bind=engine2, expire_on_commit=False)
    monkeypatch.setattr(restore_mod, "session_scope", _make_scope(Session2))

    res = await restore_mod.restore(bdir, verify=True)
    assert res["verified"]["passed"] is True
    assert res["stores"]["postgres"]["rows"] >= 6
    async with Session2() as s:
        u = (await s.execute(User.__table__.select())).mappings().first()
        assert u["username"] == "alice"  # 元数据已回灌
    await engine2.dispose()


async def test_restore_full_with_import_fakes(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    _enable_all_infra(monkeypatch)
    monkeypatch.setattr(stores, "export_milvus", _fake_export_milvus)
    monkeypatch.setattr(stores, "export_minio", _fake_export_minio)
    monkeypatch.setattr(stores, "export_opensearch", _fake_export_opensearch)
    await backup_mod.backup(out_root=tmp_path, backup_id="bk")
    bdir = tmp_path / "bk"
    await engine.dispose()

    engine2 = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True)
    async with engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session2 = async_sessionmaker(bind=engine2, expire_on_commit=False)
    monkeypatch.setattr(restore_mod, "session_scope", _make_scope(Session2))
    _enable_all_infra(monkeypatch)  # restore 端也标记可用
    monkeypatch.setattr(stores, "import_milvus", _fake_import_milvus)
    monkeypatch.setattr(stores, "import_minio", _fake_import_minio)
    monkeypatch.setattr(stores, "import_opensearch", _fake_import_opensearch)

    res = await restore_mod.restore(bdir, verify=True)
    assert res["stores"]["minio"]["objects"] == 1
    assert res["stores"]["milvus"]["collections"]["rag_chunks"]["restored"] == 1
    assert res["stores"]["opensearch"]["indexes"]["rag-chunks-default"]["restored"] == 1
    assert res["stores"]["postgres"]["rows"] >= 6
    await engine2.dispose()


async def test_restore_rejects_tampered_backup(tmp_path, monkeypatch):
    engine, Session = await _build_seeded_engine()
    monkeypatch.setattr(backup_mod, "session_scope", _make_scope(Session))
    await backup_mod.backup(out_root=tmp_path, backup_id="bk")
    await engine.dispose()

    (tmp_path / "bk" / "postgres.json").write_text("{}")  # 篡改 → sha256 不匹配
    with pytest.raises(restore_mod.VerifyError):
        await restore_mod.restore(tmp_path / "bk")
