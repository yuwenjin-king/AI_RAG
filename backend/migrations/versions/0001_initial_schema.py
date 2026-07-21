"""initial schema via metadata.create_all

首版迁移直接用 SQLAlchemy metadata 建全部表，保证 schema 与模型零漂移。
后续结构变更请用 `alembic revision --autogenerate` 生成增量迁移。

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op

from app.db.database import Base
from app.db import models  # noqa: F401  确保所有表注册

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
