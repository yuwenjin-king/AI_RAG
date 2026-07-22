"""CDC 连接器（设计书 §4.1）：消费数据源变更事件 → 增量更新索引。

事件格式（Debezium 风格，兼容简化）：
  {tenant, source, id, op: i|u|d|c, before:{...}, after:{title,text,...}}
- i/u/c：映射为文档 upsert（写对象存储 + 触发 ingest）
- d：清理该文档全部索引内容
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.repositories import document as doc_repo
from app.services import ingest as ingest_svc
from app.services.ingestion.connectors.base import ChangeEvent

log = get_logger(__name__)


@dataclass
class CDCEvent:
    tenant: str
    source: str            # 连接器/数据源标识
    object_key: str        # 业务主键（行 id 等）
    op: str                # i | u | d | c
    title: str = ""
    text: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def is_delete(self) -> bool:
        return self.op == "d"


def parse_event(raw: dict) -> CDCEvent:
    tenant = raw.get("tenant") or settings.default_tenant_id
    source = raw.get("source") or "cdc"
    op = (raw.get("op") or raw.get("operation") or "u").lower()[:1]
    obj_key = str(raw.get("id") or raw.get("key") or raw.get("object_key") or "")
    after = raw.get("after") or {}
    before = raw.get("before") or {}
    title = str(after.get("title") or before.get("title") or obj_key)
    text = str(after.get("text") or after.get("content") or "")
    return CDCEvent(
        tenant=tenant, source=source, object_key=obj_key or title,
        op=op, title=title, text=text, meta=raw.get("meta") or {"source": source},
    )


async def handle_cdc_event(session: AsyncSession, event: CDCEvent) -> Optional[int]:
    """处理单个 CDC 事件，返回受影响 doc_id（无则 None）。"""
    tenant = TenantContext(tenant_id=event.tenant)
    storage_key = f"cdc/{event.source}/{event.object_key}"

    if event.is_delete:
        # 按 object_key 找文档并清理
        from sqlalchemy import select
        from app.db.models import Document

        doc = (
            await session.execute(
                select(Document).where(
                    Document.tenant_id == event.tenant, Document.object_key == storage_key
                )
            )
        ).scalar_one_or_none()
        if doc is not None:
            await ingest_svc.delete_document(session, tenant, doc.id)
            log.info("cdc.delete source=%s key=%s doc_id=%s", event.source, event.object_key, doc.id)
            return doc.id
        return None

    if not event.text:
        log.debug("cdc.skip_no_text source=%s key=%s", event.source, event.object_key)
        return None

    # upsert：创建/复用文档记录 + 写对象存储 + 触发 ingest
    doc = await doc_repo.create_document(
        session, tenant, title=event.title or event.object_key,
        object_key=storage_key, content_type="text/plain",
        checksum=doc_repo.compute_checksum(event.text.encode("utf-8")),
        meta=event.meta,
    )
    await session.commit()
    from app.infra import object_storage
    object_storage.store_object_bytes(storage_key, event.text.encode("utf-8"), "text/plain")
    await ingest_svc.trigger_ingest(doc.id)
    log.info("cdc.upsert source=%s key=%s doc_id=%s", event.source, event.object_key, doc.id)
    return doc.id
