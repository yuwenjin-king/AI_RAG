"""备份清单（manifest）：描述一次备份包含哪些 store 产物 + sha256 校验和（plan_three §6）。

纯 dataclass + 函数，无 infra 依赖 → 离线单测重点覆盖。
manifest.json 是备份目录的"目录页 + 完整性凭证"：恢复前用它重算 sha256 确认产物未被篡改/截断。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_STORES = ("postgres", "milvus", "minio", "opensearch")

STATUS_COMPLETE = "complete"   # 全部 store 成功
STATUS_PARTIAL = "partial"     # 权威源(PG)成功，部分派生 store 降级缺失（可重建）
STATUS_FAILED = "failed"       # 权威源失败——备份不可用于恢复


@dataclass
class StoreArtifact:
    """单个 store 在备份目录中的一个产物文件。"""

    store: str                                       # postgres | milvus | minio | opensearch
    path: str                                        # 相对 backup 目录的路径
    sha256: str                                      # 产物文件 sha256（恢复前重算比对）
    size_bytes: int
    count: int                                       # 记录数：行/向量/对象/文档
    status: str = STATUS_COMPLETE
    detail: dict[str, Any] = field(default_factory=dict)  # 表/集合/索引级明细


@dataclass
class BackupManifest:
    backup_id: str
    created_at: str                                  # ISO8601（UTC）
    software_version: str
    stores: list[StoreArtifact] = field(default_factory=list)
    status: str = STATUS_COMPLETE
    notes: list[str] = field(default_factory=list)   # 降级/跳过原因
    rpo_target_seconds: int | None = None

    def store(self, name: str) -> StoreArtifact | None:
        for a in self.stores:
            if a.store == name:
                return a
        return None

    def is_recoverable(self) -> bool:
        """PG 元数据是权威源——缺它整个恢复无意义（向量/倒排可重建，原文可重传，元数据不可）。"""
        pg = self.store("postgres")
        return pg is not None and pg.status == STATUS_COMPLETE


# ===== checksum / 体积 =====
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_size(path: str | Path) -> int:
    return Path(path).stat().st_size


def make_artifact(
    store: str, file_path: Path, base_dir: Path, count: int, detail: dict[str, Any] | None = None
) -> StoreArtifact:
    """由已写好的产物文件构造 artifact（计算相对路径 + sha256 + 体积）。"""
    return StoreArtifact(
        store=store,
        path=file_path.relative_to(base_dir).as_posix(),
        sha256=sha256_file(file_path),
        size_bytes=file_size(file_path),
        count=count,
        detail=detail or {},
    )


# ===== 序列化 =====
def serialize(manifest: BackupManifest) -> str:
    """稳定 JSON（key 排序）便于 diff / 幂等复算。"""
    return json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, indent=2)


def deserialize(text: str) -> BackupManifest:
    d = json.loads(text)
    d["stores"] = [StoreArtifact(**s) for s in d.pop("stores", [])]
    return BackupManifest(**d)


def write_manifest(manifest: BackupManifest, backup_dir: str | Path) -> Path:
    p = Path(backup_dir) / "manifest.json"
    p.write_text(serialize(manifest) + "\n", encoding="utf-8")
    return p


def read_manifest(backup_dir: str | Path) -> BackupManifest:
    return deserialize((Path(backup_dir) / "manifest.json").read_text(encoding="utf-8"))


# ===== 校验 =====
@dataclass
class VerifyReport:
    ok: list[str]            # sha256 匹配的 store
    missing: list[str]       # 产物文件缺失
    mismatched: list[str]    # sha256 不匹配（篡改/截断）
    recoverable: bool        # PG 权威源是否在位

    @property
    def passed(self) -> bool:
        return not self.missing and not self.mismatched


def verify_manifest(manifest: BackupManifest, backup_dir: str | Path) -> VerifyReport:
    base = Path(backup_dir)
    ok: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for a in manifest.stores:
        p = base / a.path
        if not p.exists():
            missing.append(a.store)
            continue
        if sha256_file(p) == a.sha256:
            ok.append(a.store)
        else:
            mismatched.append(a.store)
    return VerifyReport(ok=ok, missing=missing, mismatched=mismatched, recoverable=manifest.is_recoverable())
