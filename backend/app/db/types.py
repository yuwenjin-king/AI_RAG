"""可移植类型：PostgreSQL 上用 JSONB，其它后端（如 sqlite 测试）回退 JSON。"""
from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB

JSONB = JSON().with_variant(_PG_JSONB(), "postgresql")
