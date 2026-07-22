"""CDC 事件处理 + DB 差量连接器测试（sqlite）。"""
import pytest

from app.core.config import settings as cfg
from app.services.ingestion.connectors import cdc as cdc_mod
from app.services.ingestion.connectors import db as db_mod


@pytest.mark.asyncio
async def test_parse_event_upsert_and_delete(monkeypatch):
    monkeypatch.setattr(cfg, "sync_ingest_fallback", False)
    ev = cdc_mod.parse_event(
        {"tenant": "A", "source": "wiki", "id": "p1", "op": "update",
         "after": {"title": "T", "text": "hello"}}
    )
    assert ev.op == "u" and not ev.is_delete
    assert ev.title == "T" and ev.text == "hello"

    ev_d = cdc_mod.parse_event({"tenant": "A", "source": "wiki", "id": "p1", "op": "d"})
    assert ev_d.is_delete


@pytest.mark.asyncio
async def test_handle_cdc_upsert_then_delete(sqlite_session, monkeypatch):
    monkeypatch.setattr(cfg, "sync_ingest_fallback", False)
    ev = cdc_mod.parse_event(
        {"tenant": "A", "source": "wiki", "id": "p1", "op": "u",
         "after": {"title": "T", "text": "hello world"}}
    )
    doc_id = await cdc_mod.handle_cdc_event(sqlite_session, ev)
    assert doc_id is not None

    # delete 事件（按 storage_key cdc/wiki/p1 定位）→ 清理
    ev_d = cdc_mod.parse_event({"tenant": "A", "source": "wiki", "id": "p1", "op": "d"})
    deleted_id = await cdc_mod.handle_cdc_event(sqlite_session, ev_d)
    assert deleted_id == doc_id


@pytest.mark.asyncio
async def test_db_connector_diff_and_sync(sqlite_session, monkeypatch):
    monkeypatch.setattr(cfg, "sync_ingest_fallback", False)
    conn = db_mod.DatabaseConnector(
        source="db1", tenant_id="A", dsn="", table="t",
        id_col="id", title_col="t", text_col="c",
    )
    rows = [
        {"id": 1, "t": "alpha doc", "c": "alpha beta"},
        {"id": 2, "t": "beta doc", "c": "gamma delta"},
    ]
    r1 = await conn.diff_and_sync(sqlite_session, rows)
    assert len(r1["upserted"]) == 2 and r1["deleted"] == []

    # 相同快照再同步 → 无变更
    r2 = await conn.diff_and_sync(sqlite_session, rows)
    assert r2["upserted"] == [] and r2["deleted"] == []

    # 修改 row1 → 1 个 upsert
    rows[0]["c"] = "alpha beta changed"
    r3 = await conn.diff_and_sync(sqlite_session, rows)
    assert len(r3["upserted"]) == 1

    # 移除 row2 → 1 个 delete
    r4 = await conn.diff_and_sync(sqlite_session, [rows[0]])
    assert len(r4["deleted"]) == 1
