"""恢复编排：读 manifest → sha256 校验 → 依赖序恢复（plan_three §6）。

恢复顺序：MinIO（原文）→ PG（元数据，权威）→ Milvus（向量）→ OpenSearch（倒排）。
理由：向量/倒排引用 doc/chunk id（来自 PG），故 PG 必须先于二者；MinIO 原文无强依赖，先行。

破坏性：PG 按"子→父清空 + 父→子回灌"使目标 == 备份；CLI 层要求 --yes/交互确认。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.db.database import session_scope
from app.infra import milvus_store, object_storage, opensearch_store
from app.scripts.dr import manifest as M
from app.scripts.dr import pg_meta, stores

log = get_logger(__name__)


class VerifyError(RuntimeError):
    """备份完整性校验失败（文件缺失/sha256 不匹配/权威源缺失）。"""


async def restore(backup_dir: str | Path, *, verify: bool = True) -> dict[str, Any]:
    bdir = Path(backup_dir)
    man = M.read_manifest(bdir)
    result: dict[str, Any] = {"backup_id": man.backup_id, "status": man.status, "stores": {}, "verified": None}

    if verify:
        report = M.verify_manifest(man, bdir)
        result["verified"] = {
            "ok": report.ok,
            "missing": report.missing,
            "mismatched": report.mismatched,
            "passed": report.passed,
        }
        if report.missing or report.mismatched:
            raise VerifyError(f"backup integrity check failed: missing={report.missing} mismatched={report.mismatched}")
        if not man.is_recoverable():
            raise VerifyError("backup not recoverable: postgres artifact missing/incomplete")

    # 1) MinIO 原文
    a_minio = man.store("minio")
    if a_minio and object_storage.is_available():
        _, detail = stores.import_minio(bdir / a_minio.path)
        result["stores"]["minio"] = detail
    elif a_minio:
        result["stores"]["minio"] = {"skipped": "object storage unavailable"}

    # 2) PG 元数据（权威源）
    a_pg = man.store("postgres")
    if a_pg:
        data = pg_meta.read_metadata(bdir / a_pg.path)
        async with session_scope() as session:
            n = await pg_meta.restore_metadata(session, data)
        result["stores"]["postgres"] = {"rows": n, "tables": {t: len(r) for t, r in data.items()}}

    # 3) Milvus 向量（依赖 PG 的 doc/chunk id）
    a_milvus = man.store("milvus")
    if a_milvus and milvus_store.is_available():
        _, detail = await stores.import_milvus(bdir / a_milvus.path)
        result["stores"]["milvus"] = detail
    elif a_milvus:
        result["stores"]["milvus"] = {"skipped": "milvus unavailable (re-embed chunks to rebuild)"}

    # 4) OpenSearch 倒排（可由 chunks 重建）
    a_os = man.store("opensearch")
    if a_os and opensearch_store.is_available():
        _, detail = await stores.import_opensearch(bdir / a_os.path)
        result["stores"]["opensearch"] = detail
    elif a_os:
        result["stores"]["opensearch"] = {"skipped": "opensearch unavailable (re-index chunks to rebuild)"}

    return result
