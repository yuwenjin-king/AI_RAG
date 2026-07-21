"""对象存储（MinIO/S3）：原文档、页面渲染图缓存。

提供：预签名上传/下载 URL、直接读取、删除。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import os

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client = None  # minio.Minio
_available = False


def init_object_storage() -> None:
    global _client, _available
    try:
        from minio import Minio

        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        if not _client.bucket_exists(settings.minio_bucket):
            _client.make_bucket(settings.minio_bucket)
            log.info("minio.bucket_created bucket=%s", settings.minio_bucket)
        _available = True
        log.info("minio.connected endpoint=%s", settings.minio_endpoint)
    except Exception as e:  # noqa: BLE001
        _available = False
        log.warning("minio.unavailable degraded_object_storage (err=%s)", e)


def is_available() -> bool:
    return _available


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
