"""各 store 的导出/导入 + tar 打包（plan_three §6 DR）。

每个 store 产出**单个 tar/json 文件**（便于 manifest 计算一个 sha256）：
- milvus/opensearch：tar 内每集合/索引一个 .jsonl
- minio：tar 内每个对象以其 key 为成员名
infra 不可用时各 infra 函数返回空/0 + 由上层标记 degraded（见 backup.py）。
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.infra import milvus_store, object_storage, opensearch_store

log = get_logger(__name__)


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _read_jsonl(member: tarfile.TarInfo, tar: tarfile.TarFile) -> list[dict[str, Any]]:
    f = tar.extractfile(member)
    if f is None:
        return []
    return [json.loads(line) for line in f.read().decode("utf-8").splitlines() if line.strip()]


def _write_jsonl(recs: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + ("\n" if recs else "")).encode("utf-8")


# ===== Milvus：collection → tar(jsonl per collection) =====
async def export_milvus(out_path: str | Path) -> tuple[int, dict[str, Any]]:
    cols = await milvus_store.list_rag_collections()
    total = 0
    detail: dict[str, Any] = {"collections": {}}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name in cols:
            recs = await milvus_store.export_collection(name)
            total += len(recs)
            detail["collections"][name] = len(recs)
            _add_bytes(tar, f"{name}.jsonl", _write_jsonl(recs))
    Path(out_path).write_bytes(buf.getvalue())
    return total, detail


async def import_milvus(tar_path: str | Path) -> tuple[int, dict[str, Any]]:
    detail: dict[str, Any] = {"collections": {}}
    total = 0
    with tarfile.open(tar_path, mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".jsonl"):
                continue
            name = member.name[: -len(".jsonl")]
            recs = _read_jsonl(member, tar)
            n = await milvus_store.import_collection(name, recs)
            total += n
            detail["collections"][name] = {"restored": n, "expected": len(recs)}
    return total, detail


# ===== MinIO：bucket → tar(objects) =====
def export_minio(out_path: str | Path) -> tuple[int, dict[str, Any]]:
    keys = object_storage.list_object_keys()
    total = 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for key in keys:
            try:
                data = object_storage.get_bytes(key)
            except Exception as e:  # noqa: BLE001
                log.warning("dr.minio.skip key=%s err=%s", key, e)
                continue
            _add_bytes(tar, key, data)
            total += 1
    Path(out_path).write_bytes(buf.getvalue())
    return total, {"objects": total}


def import_minio(tar_path: str | Path) -> tuple[int, dict[str, Any]]:
    n = 0
    with tarfile.open(tar_path, mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            try:
                object_storage.put_bytes(member.name, f.read())
                n += 1
            except Exception as e:  # noqa: BLE001
                log.warning("dr.minio.restore_skip key=%s err=%s", member.name, e)
    return n, {"objects": n}


# ===== OpenSearch：index → tar(jsonl per index) =====
async def export_opensearch(out_path: str | Path) -> tuple[int, dict[str, Any]]:
    idxs = await opensearch_store.list_rag_indexes()
    total = 0
    detail: dict[str, Any] = {"indexes": {}}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for idx in idxs:
            docs = await opensearch_store.export_index(idx)
            total += len(docs)
            detail["indexes"][idx] = len(docs)
            _add_bytes(tar, f"{idx}.jsonl", _write_jsonl(docs))
    Path(out_path).write_bytes(buf.getvalue())
    return total, detail


async def import_opensearch(tar_path: str | Path) -> tuple[int, dict[str, Any]]:
    detail: dict[str, Any] = {"indexes": {}}
    total = 0
    with tarfile.open(tar_path, mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".jsonl"):
                continue
            idx = member.name[: -len(".jsonl")]
            docs = _read_jsonl(member, tar)
            await opensearch_store.ensure_index_by_name(idx)
            n = await opensearch_store.bulk_index(idx, docs)
            total += n
            detail["indexes"][idx] = {"restored": n, "expected": len(docs)}
    return total, detail
