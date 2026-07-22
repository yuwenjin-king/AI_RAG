"""数据库连接器（设计书 §4.1）：周期轮询 + hash/timestamp 差量增量。

非 CDC（非 Debezium）场景的增量接入：每次轮询全表，与上次快照按 checksum/timestamp
比对，仅对新增/变更行触发 ingest，对消失行做删除清理。
CDC（Debezium）事件驱动路径见 connectors/cdc.py。
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.tenant import TenantContext
from app.repositories import document as doc_repo
from app.services import ingest as ingest_svc
from app.services.ingestion.sync import DocFingerprint, HashTimestampDetector

log = get_logger(__name__)


def _checksum(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class DatabaseConnector:
    """轮询一张表，按差量同步到 RAG 索引。"""

    def __init__(
        self, *, source: str, tenant_id: str, dsn: str, table: str,
        id_col: str = "id", title_col: str = "title", text_col: str = "text", ts_col: Optional[str] = None,
    ):
        self.source = source
        self.tenant_id = tenant_id
        self.dsn = dsn
        self.table = table
        self.id_col, self.title_col, self.text_col, self.ts_col = id_col, title_col, text_col, ts_col
        self._seen: dict[str, DocFingerprint] = {}
        self._detector = HashTimestampDetector()

    async def fetch_rows(self) -> List[dict]:
        import asyncpg

        conn = await asyncpg.connect(self.dsn)
        try:
            cols = [self.id_col, self.title_col, self.text_col]
            if self.ts_col:
                cols.append(self.ts_col)
            rows = await conn.fetch(f'SELECT {", ".join(cols)} FROM {self.table}')
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def diff_and_sync(self, session: AsyncSession, rows: List[dict]) -> dict:
        """对当次拉取的 rows 做差量同步：返回 {created_or_updated, deleted}。"""
        from app.infra import object_storage

        tenant = TenantContext(self.tenant_id)
        fp_by_key: dict[str, tuple[DocFingerprint, dict]] = {}
        for r in rows:
            key = str(r.get(self.id_col))
            text = str(r.get(self.text_col) or "")
            mtime = float(r.get(self.ts_col)) if self.ts_col and r.get(self.ts_col) else None
            fp_by_key[key] = (DocFingerprint(object_key=key, checksum=_checksum(text), mtime=mtime), r)

        current = {k: v[0] for k, v in fp_by_key.items()}
        changed = self._detector.diff(self._seen, list(current.values()))
        changed_keys = {c.object_key for c in changed}
        deleted_keys = [k for k in self._seen if k not in current]

        upserted: List[int] = []
        for key, (fp, row) in fp_by_key.items():
            if key not in changed_keys:
                continue
            storage_key = f"db/{self.source}/{key}"
            title = str(row.get(self.title_col) or key)
            text = str(row.get(self.text_col) or "")
            doc = await doc_repo.create_document(
                session, tenant, title=title, object_key=storage_key,
                content_type="text/plain", checksum=fp.checksum, meta={"source": self.source},
            )
            await session.commit()
            object_storage.store_object_bytes(storage_key, text.encode("utf-8"), "text/plain")
            await ingest_svc.trigger_ingest(doc.id)
            upserted.append(doc.id)

        deleted: List[int] = []
        for key in deleted_keys:
            storage_key = f"db/{self.source}/{key}"
            from sqlalchemy import select
            from app.db.models import Document

            doc = (
                await session.execute(
                    select(Document).where(
                        Document.tenant_id == self.tenant_id, Document.object_key == storage_key
                    )
                )
            ).scalar_one_or_none()
            if doc is not None:
                await ingest_svc.delete_document(session, tenant, doc.id)
                deleted.append(doc.id)

        self._seen = current
        return {"upserted": upserted, "deleted": deleted}

    async def poll_once(self, session: AsyncSession) -> dict:
        rows = await self.fetch_rows()
        return await self.diff_and_sync(session, rows)
