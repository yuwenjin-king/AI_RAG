"""PostgreSQL 元数据便携式 dump/restore（plan_three §6）。

实现：SQLAlchemy 行级 JSON。`Base.metadata.sorted_tables` 给出 FK 拓扑序——
导出按父→子、恢复按子→父清空再父→子回灌，ID 原样保留（FK 一致）。
asyncpg / aiosqlite 通用 → 可用 sqlite 离线单测（见 tests/test_dr.py）。

值用类型自描述标签编码（{"__iso__": ...} 等），恢复端无需列类型即可还原，
故 datetime/Decimal/UUID/bytes/JSONB 均可无损往返。

生产推荐 `pg_dump` + WAL 归档（PITR，类型/约束/序列完全保真，见 docs/dr-runbook.md）；
本模块是无 pg 客户端 / 跨方言（含 sqlite 测试）时的可移植兜底。
"""
from __future__ import annotations

import base64
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Base

log = get_logger(__name__)


# ===== 类型自描述编码/解码（恢复端无需列类型即可还原） =====
def _encode(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dt.datetime):
        return {"__iso__": v.isoformat()}
    if isinstance(v, dt.date):  # date 是 datetime 父类，放后面
        return {"__date__": v.isoformat()}
    if isinstance(v, dt.time):
        return {"__time__": v.isoformat()}
    if isinstance(v, Decimal):
        return {"__dec__": str(v)}
    if isinstance(v, UUID):
        return {"__uuid__": str(v)}
    if isinstance(v, (bytes, bytearray)):
        return {"__bytes__": base64.b64encode(bytes(v)).decode("ascii")}
    return v  # dict/list（JSONB）原样


def _decode(v: Any) -> Any:
    if isinstance(v, dict):
        if "__iso__" in v:
            return dt.datetime.fromisoformat(v["__iso__"])
        if "__date__" in v:
            return dt.date.fromisoformat(v["__date__"])
        if "__time__" in v:
            return dt.time.fromisoformat(v["__time__"])
        if "__dec__" in v:
            return Decimal(v["__dec__"])
        if "__uuid__" in v:
            return UUID(v["__uuid__"])
        if "__bytes__" in v:
            return base64.b64decode(v["__bytes__"])
    return v


# ===== dump =====
async def dump_metadata(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """导出全部表行（FK 拓扑序，父→子），返回 {table_name: [row,...]}。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        rows = (await session.execute(table.select())).mappings().all()
        out[table.name] = [{k: _encode(v) for k, v in dict(r).items()} for r in rows]
    return out


def write_metadata(data: dict[str, list[dict[str, Any]]], path: str | Path) -> int:
    """写单个 JSON 文件；返回总行数。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return sum(len(rows) for rows in data.values())


def read_metadata(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ===== restore =====
async def restore_metadata(session: AsyncSession, data: dict[str, list[dict[str, Any]]]) -> int:
    """反向清空（子→父）+ 正向回灌（父→子），使目标 == 备份。返回插入行数。

    显式插入主键（含自增列），保证 doc/chunk 等编号一致 → Milvus/OS 的外键引用成立。
    """
    ordered = Base.metadata.sorted_tables
    names = set(data.keys())
    for table in reversed(ordered):              # 子→父删
        if table.name in names:
            await session.execute(table.delete())
    inserted = 0
    for table in ordered:                        # 父→子插
        rows = data.get(table.name)
        if not rows:
            continue
        payload = [{k: _decode(v) for k, v in row.items()} for row in rows]
        await session.execute(table.insert(), payload)
        inserted += len(payload)
    return inserted
