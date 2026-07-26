"""对象存储（MinIO/S3）：原文档、页面渲染图缓存。

提供：预签名上传/下载 URL、直接读取、删除。
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

import os

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client = None  # minio.Minio
_available = False


def init_object_storage(*, retries: int = 10, delay: float = 2.0) -> None:
    """初始化 MinIO 并确保 bucket 存在。

    minio 容器无健康检查门控，启动时序由这里的重试容忍：失败重试最多 `retries` 次。
    最终不可用则降级（_available=False，本地存储兜底）。
    """
    global _client, _available
    from minio import Minio

    _client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if not _client.bucket_exists(settings.minio_bucket):
                _client.make_bucket(settings.minio_bucket)
                log.info("minio.bucket_created bucket=%s", settings.minio_bucket)
            _enable_versioning(_client, settings.minio_bucket)
            _available = True
            log.info("minio.connected endpoint=%s", settings.minio_endpoint)
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.info("minio.connect.retry attempt=%s/%s err=%s", attempt, retries, e)
            time.sleep(delay)
    _available = False
    log.warning("minio.unavailable degraded_object_storage (err=%s)", last_err)


def is_available() -> bool:
    return _available


def _enable_versioning(client, bucket: str) -> None:
    """启用 bucket 版本化（对象级历史 / 误删保护，plan_three §6）。best-effort：旧 MinIO 或禁用时不阻断。"""
    if not settings.minio_bucket_versioning:
        return
    try:
        from minio.versioningconfig import VersioningConfig

        client.set_bucket_versioning(bucket, VersioningConfig("Enabled"))
        log.info("minio.versioning_enabled bucket=%s", bucket)
    except Exception as e:  # noqa: BLE001
        log.info("minio.versioning.skipped bucket=%s err=%s", bucket, e)


def list_object_keys() -> list[str]:
    """枚举 bucket 内全部对象 key（DR 备份用）。不可用→[]。"""
    if not _available or _client is None:
        return []
    try:
        return [o.object_name for o in _client.list_objects(settings.minio_bucket, prefix="", recursive=True)]
    except Exception as e:  # noqa: BLE001
        log.warning("object_storage.list_objects.failed err=%s", e)
        return []


def presigned_upload(object_key: str, expires_minutes: int = 15) -> str:
    """返回前端直传用预签名 PUT URL。"""
    if not _available or _client is None:
        raise RuntimeError("object storage unavailable")
    return _client.presigned_put_object(
        settings.minio_bucket, object_key, expires=timedelta(minutes=expires_minutes)
    )


def presigned_download(object_key: str, expires_minutes: int = 30) -> str:
    if not _available or _client is None:
        raise RuntimeError("object storage unavailable")
    return _client.presigned_get_object(
        settings.minio_bucket, object_key, expires=timedelta(minutes=expires_minutes)
    )


def get_bytes(object_key: str) -> bytes:
    """同步读取对象全文（worker 解析时用）。"""
    if not _available or _client is None:
        raise RuntimeError("object storage unavailable")
    resp = _client.get_object(settings.minio_bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def put_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if not _available or _client is None:
        raise RuntimeError("object storage unavailable")
    import io

    _client.put_object(
        settings.minio_bucket, object_key, io.BytesIO(data), length=len(data), content_type=content_type
    )


def remove_object(object_key: str) -> None:
    if not _available or _client is None:
        return
    try:
        _client.remove_object(settings.minio_bucket, object_key)
    except Exception:  # noqa: BLE001
        pass


# ===== 本地存储兜底（MinIO 不可用时使用，保证最小链路可跑通） =====
def _local_path(object_key: str) -> str:
    safe = object_key.replace("/", "_")
    d = settings.local_store_dir
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, safe)


def local_put_bytes(object_key: str, data: bytes) -> None:
    with open(_local_path(object_key), "wb") as f:
        f.write(data)


def local_get_bytes(object_key: str) -> bytes:
    with open(_local_path(object_key), "rb") as f:
        return f.read()


def local_exists(object_key: str) -> bool:
    return os.path.exists(_local_path(object_key))


def get_object_bytes(object_key: str) -> bytes:
    """优先 MinIO，回退本地存储。"""
    if is_available():
        try:
            return get_bytes(object_key)
        except Exception as e:  # noqa: BLE001
            log.warning("object_storage.minio_read_failed fallback_local err=%s", e)
    return local_get_bytes(object_key)


def store_object_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """优先 MinIO，回退本地存储。"""
    if is_available():
        try:
            put_bytes(object_key, data, content_type)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("object_storage.minio_write_failed fallback_local err=%s", e)
    local_put_bytes(object_key, data)


def object_exists(object_key: str) -> bool:
    if is_available():
        try:
            from minio.commonconfig import CopySource  # noqa: F401
            _client.stat_object(settings.minio_bucket, object_key)
            return True
        except Exception:
            return False
    return local_exists(object_key)
