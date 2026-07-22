"""eval cases + scene variants

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22

幂等：0001 用 metadata.create_all（反映当前模型），fresh DB 已建好 eval_cases 与
scene_configs.variants；本迁移仅在"旧 DB（0001 跑过更早模型版本）"上补建。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = insp.get_table_names()

    if "eval_cases" not in tables:
        op.create_table(
            "eval_cases",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("scene_id", sa.String(64), nullable=True),
            sa.Column("query", sa.Text, nullable=False),
            sa.Column("expected_answer", sa.Text, nullable=True),
            sa.Column("expected_doc_ids", JSONB, nullable=True),
            sa.Column("expected_page", sa.Integer, nullable=True),
            sa.Column("expected_bbox", JSONB, nullable=True),
            sa.Column("tags", JSONB, nullable=True),
            sa.Column("meta", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_eval_cases_tenant_id", "eval_cases", ["tenant_id"])
        op.create_index("ix_eval_cases_scene_id", "eval_cases", ["scene_id"])
        op.create_index("ix_evalcase_tenant_scene", "eval_cases", ["tenant_id", "scene_id"])

    if "scene_configs" in tables:
        cols = [c["name"] for c in insp.get_columns("scene_configs")]
        if "variants" not in cols:
            op.add_column("scene_configs", sa.Column("variants", JSONB, nullable=True))

    if "messages" in tables:
        cols = [c["name"] for c in insp.get_columns("messages")]
        if "meta" not in cols:
            op.add_column("messages", sa.Column("meta", JSONB, nullable=True))


def downgrade() -> None:
    insp = _inspector()
    if "messages" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("messages")]
        if "meta" in cols:
            op.drop_column("messages", "meta")
    if "scene_configs" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("scene_configs")]
        if "variants" in cols:
            op.drop_column("scene_configs", "variants")
    if "eval_cases" in insp.get_table_names():
        op.drop_table("eval_cases")
