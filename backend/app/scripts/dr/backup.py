"""备份编排：dump 全部 store → 备份目录 + manifest（plan_three §6）。

PG 元数据是权威源，始终备份（便携 JSON，asyncpg/sqlite 通用）；
Milvus/MinIO/OpenSearch 各自 best-effort，不可用则记 degraded（恢复时可从 PG 重建/重传）。
"""
from __future__ import annotations

import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import session_scope
from app.infra import milvus_store, object_storage, opensearch_store
from app.scripts.dr import manifest as M
from app.scripts.dr import pg_meta, stores

log = get_logger(__name__)

SOFTWARE_VERSION = "0.1.0"


def new_backup_id() -> str:
    """UTC 时间戳 + 短随机后缀（避免同秒冲突；目录名即排序键）。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)


def _prune_old(backups_root: Path, retention: int) -> list[str]:
    """超出保留数的旧备份删除（按目录名排序，留最新 N）。返回被删目录名。"""
    if retention <= 0:
        return []
    dirs = sorted(d for d in backups_root.glob("*/") if (d / "manifest.json").exists())
    excess = dirs[: max(0, len(dirs) - retention)]
    removed: list[str] = []
    for d in excess:
        try:
            shutil.rmtree(d)
            removed.append(d.name)
        except Exception as e:  # noqa: BLE001
            log.warning("dr.prune.skip %s err=%s", d, e)
    return removed


async def backup(out_root: str | Path | None = None, *, backup_id: str | None = None) -> M.BackupManifest:
    root = Path(out_root or settings.backup_dir)
    bid = backup_id or new_backup_id()
    bdir = root / bid
    bdir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    artifacts: list[M.StoreArtifact] = []

    # 1) PG 元数据（权威源，始终备份）
    async with session_scope() as session:
        data = await pg_meta.dump_metadata(session)
    pg_path = bdir / "postgres.json"
    count = pg_meta.write_metadata(data, pg_path)
    artifacts.append(M.make_artifact("postgres", pg_path, bdir, count, detail={t: len(r) for t, r in data.items()}))
    log.info("dr.backup.postgres rows=%s", count)

    # 2) Milvus（向量；不可用→恢复时按 chunk 重新 embed，记 degraded）
    if milvus_store.is_available():
        try:
            mp = bdir / "milvus.tar"
            n, detail = await stores.export_milvus(mp)
            artifacts.append(M.make_artifact("milvus", mp, bdir, n, detail))
            log.info("dr.backup.milvus vectors=%s", n)
        except Exception as e:  # noqa: BLE001
            notes.append(f"milvus export failed: {e}")
    else:
        notes.append("milvus unavailable: vectors not backed up (re-embeddable from chunks on restore)")

    # 3) MinIO（原文档；不可用→记 degraded，原文需重传）
    if object_storage.is_available():
        try:
            np = bdir / "minio.tar"
            n, detail = stores.export_minio(np)
            artifacts.append(M.make_artifact("minio", np, bdir, n, detail))
            log.info("dr.backup.minio objects=%s", n)
        except Exception as e:  # noqa: BLE001
            notes.append(f"minio export failed: {e}")
    else:
        notes.append("minio unavailable: original documents not backed up")

    # 4) OpenSearch（倒排；可从 chunks 完全重建，按需关闭）
    if settings.backup_include_opensearch and opensearch_store.is_available():
        try:
            op = bdir / "opensearch.tar"
            n, detail = await stores.export_opensearch(op)
            artifacts.append(M.make_artifact("opensearch", op, bdir, n, detail))
            log.info("dr.backup.opensearch docs=%s", n)
        except Exception as e:  # noqa: BLE001
            notes.append(f"opensearch export failed: {e}")
    elif not settings.backup_include_opensearch:
        notes.append("opensearch skipped (backup_include_opensearch=false; rebuildable via re-index)")

    status = M.STATUS_COMPLETE
    if not milvus_store.is_available() or not object_storage.is_available():
        status = M.STATUS_PARTIAL  # 权威源(PG)在，派生 store 缺——仍可恢复（重建向量/重传原文）

    man = M.BackupManifest(
        backup_id=bid,
        created_at=datetime.now(timezone.utc).isoformat(),
        software_version=SOFTWARE_VERSION,
        stores=artifacts,
        status=status,
        notes=notes,
        rpo_target_seconds=settings.backup_rpo_target_seconds,
    )
    M.write_manifest(man, bdir)

    removed = _prune_old(root, settings.backup_retention)
    if removed:
        log.info("dr.prune removed=%s", removed)
    return man
