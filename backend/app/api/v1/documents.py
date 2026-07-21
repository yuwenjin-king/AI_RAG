"""文档 API：预签名上传、直传、列表、区域级溯源定位（设计书 §5.5）。"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_tenant_ctx
from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.db.database import session_scope
from app.infra import kafka_bus, object_storage
from app.repositories import document as doc_repo
from app.schemas.common import LocateOut, Page
from app.schemas.entities import (
    DocumentListFilter,
    DocumentOut,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.ingest import process_document

router = APIRouter()
log = get_logger(__name__)


def _object_key(tenant: str, filename: str) -> str:
    return f"{tenant}/{uuid.uuid4().hex}/{filename}"


async def _enqueue_or_sync(doc_id: int) -> None:
    """发布到 Kafka；不可用则同步兜底处理。"""
    ok = await kafka_bus.produce(
        settings.kafka_ingest_topic, {"doc_id": doc_id}, key=str(doc_id)
    )
    if not ok and settings.sync_ingest_fallback:
        log.info("document.ingest.sync_fallback doc_id=%s", doc_id)
        # 后台任务处理，避免阻塞上传响应
        asyncio.create_task(_sync_ingest(doc_id))


async def _sync_ingest(doc_id: int) -> None:
    try:
        async with session_scope() as s:
            await process_document(s, doc_id)
    except Exception as e:  # noqa: BLE001
        log.error("document.ingest.sync_failed doc_id=%s err=%s", doc_id, e)


@router.post("/documents/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(
    req: UploadUrlRequest,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    """创建文档记录并返回上传方式。MinIO 可用→预签名 PUT；否则→直传入口。"""
    object_key = _object_key(tenant.tenant_id, req.filename)
    doc = await doc_repo.create_document(
        session, tenant,
        title=req.filename, object_key=object_key, content_type=req.content_type,
        knowledge_base_id=req.knowledge_base_id,
    )
    await session.commit()

    upload_url = None
    direct_url = None
    if object_storage.is_available():
        try:
            upload_url = object_storage.presigned_upload(object_key)
        except Exception as e:  # noqa: BLE001
            log.warning("document.presign.failed err=%s", e)
    if not upload_url:
        direct_url = f"/api/v1/documents/{doc.id}/upload"

    return UploadUrlResponse(
        doc_id=doc.id, object_key=object_key, upload_url=upload_url, direct_upload_url=direct_url,
    )


@router.post("/documents/{doc_id}/upload", response_model=DocumentOut)
async def direct_upload(
    doc_id: int,
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    """直传文件（MinIO 不可用或小文件便捷上传）。存对象存储后触发处理管线。"""
    doc = await doc_repo.get_document(session, tenant, doc_id)
    data = await file.read()
    checksum = doc_repo.compute_checksum(data)
    object_storage.store_object_bytes(doc.object_key, data, file.content_type or doc.content_type)

    doc.size_bytes = len(data)
    doc.checksum = checksum
    if file.content_type:
        doc.content_type = file.content_type
    await session.commit()

    await _enqueue_or_sync(doc_id)
    return doc


@router.post("/documents/{doc_id}/finalize", response_model=DocumentOut)
async def finalize_upload(
    doc_id: int,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    """预签名 PUT 上传完成后调用，触发处理管线。"""
    doc = await doc_repo.get_document(session, tenant, doc_id)
    await _enqueue_or_sync(doc_id)
    return doc


@router.get("/documents", response_model=Page[DocumentOut])
async def list_documents(
    knowledge_base_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    rows, total = await doc_repo.list_documents(
        session, tenant,
        knowledge_base_id=knowledge_base_id, status=status, page=page, page_size=page_size,
    )
    return Page(items=rows, total=total, page=page, page_size=page_size)


@router.get("/documents/{doc_id}/locate", response_model=LocateOut)
async def locate(
    doc_id: int,
    chunk_id: int,
    tenant: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    """区域级溯源：返回 chunk 的 page_no + bbox + 文档预览 URL（前端 PDF.js 高亮）。"""
    chunk = await doc_repo.get_chunk(session, tenant, chunk_id)
    doc = await doc_repo.get_document(session, tenant, doc_id)
    preview_url = None
    if object_storage.is_available():
        try:
            preview_url = object_storage.presigned_download(doc.object_key)
        except Exception:  # noqa: BLE001
            preview_url = None
    return LocateOut(
        chunk_id=chunk.id, doc_id=doc.id, title=doc.title,
        page_no=chunk.page_no, bbox=chunk.bbox, preview_url=preview_url,
    )
