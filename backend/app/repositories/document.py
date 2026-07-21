"""文档 / Chunk 仓储（租户隔离；chunk 冗余 tenant_id 供检索前置过滤）。"""
from __future__ import annotations

import hashlib
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.db.models import Chunk, Document, DocumentStatus


# ---------- 文档 ----------
async def create_document(
    session: AsyncSession, tenant: TenantContext, *,
    title: str, object_key: str, content_type: str = "application/octet-stream",
    size_bytes: int = 0, checksum: Optional[str] = None, knowledge_base_id: Optional[int] = None,
    meta: Optional[dict] = None,
) -> Document:
    doc = Document(
        tenant_id=tenant.tenant_id, title=title, object_key=object_key,
        content_type=content_type, size_bytes=size_bytes, checksum=checksum,
        knowledge_base_id=knowledge_base_id, meta=meta or {},
        status=DocumentStatus.PENDING.value,
    )
    session.add(doc)
    await session.flush()
    return doc


async def get_document(session: AsyncSession, tenant: TenantContext, doc_id: int) -> Document:
    obj = (
        await session.execute(
            select(Document).where(Document.id == doc_id, Document.tenant_id == tenant.tenant_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError(f"document {doc_id} not found")
    return obj


async def list_documents(
    session: AsyncSession, tenant: TenantContext, *,
    knowledge_base_id: Optional[int] = None, status: Optional[str] = None,
    page: int = 1, page_size: int = 20,
):
    base = select(Document).where(Document.tenant_id == tenant.tenant_id)
    if knowledge_base_id is not None:
        base = base.where(Document.knowledge_base_id == knowledge_base_id)
    if status:
        base = base.where(Document.status == status)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(Document.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def set_status(
    session: AsyncSession, tenant: TenantContext, doc_id: int, status: DocumentStatus,
    *, embedding_status: Optional[str] = None, error: Optional[str] = None,
    meta_patch: Optional[dict] = None,
) -> None:
    doc = await get_document(session, tenant, doc_id)
    doc.status = status.value
    if embedding_status:
        doc.embedding_status = embedding_status
    doc.error = error
    if meta_patch:
        doc.meta = {**(doc.meta or {}), **meta_patch}
    await session.flush()


# ---------- Chunk ----------
async def add_chunks(session: AsyncSession, chunks: Sequence[dict]) -> list[Chunk]:
    """批量写入 chunk（已含 tenant_id/document_id）。返回刷新后的对象（含 id）。"""
    objs = [Chunk(**c) for c in chunks]
    session.add_all(objs)
    await session.flush()
    return objs


async def delete_chunks_for_doc(
    session: AsyncSession, tenant: TenantContext, doc_id: int
) -> None:
    """删除文档的全部 chunk（视觉重处理前清理旧索引内容用）。"""
    from sqlalchemy import delete as sa_delete

    await session.execute(
        sa_delete(Chunk).where(
            Chunk.document_id == doc_id, Chunk.tenant_id == tenant.tenant_id
        )
    )
    await session.flush()


async def get_chunk(session: AsyncSession, tenant: TenantContext, chunk_id: int) -> Chunk:
    obj = (
        await session.execute(
            select(Chunk).where(Chunk.id == chunk_id, Chunk.tenant_id == tenant.tenant_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError(f"chunk {chunk_id} not found")
    return obj


async def fetch_enriched(
    session: AsyncSession, tenant: TenantContext, chunk_ids: Iterable[int]
) -> list[dict]:
    """根据 chunk_id 批量取 chunk + 文档标题/页码/bbox + 父块内容（Small-to-Big 回溯）。"""
    ids = [c for c in chunk_ids if c is not None]
    if not ids:
        return []
    rows = (
        await session.execute(
            select(Chunk, Document.title)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(ids), Chunk.tenant_id == tenant.tenant_id)
        )
    ).all()
    # 一次性取所有父块内容
    parent_ids = {c.parent_chunk_id for c, _ in rows if c.parent_chunk_id}
    parent_content: dict[int, str] = {}
    if parent_ids:
        parents = (
            await session.execute(
                select(Chunk.id, Chunk.content).where(
                    Chunk.id.in_(parent_ids), Chunk.tenant_id == tenant.tenant_id
                )
            )
        ).all()
        parent_content = {pid: (txt or "") for pid, txt in parents}
    return [
        {
            "chunk_id": c.id,
            "document_id": c.document_id,
            "content": c.content,
            "page_no": c.page_no,
            "bbox": c.bbox,
            "title": title,
            "parent_chunk_id": c.parent_chunk_id,
            "context": parent_content.get(c.parent_chunk_id, c.content) if c.parent_chunk_id else c.content,
        }
        for c, title in rows
    ]


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
