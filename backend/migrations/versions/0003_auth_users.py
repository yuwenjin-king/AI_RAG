"""auth: users + user_tenant_memberships

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23

幂等：fresh DB 经 metadata.create_all 已建表；本迁移仅在"跑过更早模型版本的旧 DB"上补建。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = insp.get_table_names()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String(64), nullable=False),
            sa.Column("email", sa.String(128), nullable=True),
            sa.Column("password_hash", sa.String(256), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=True, server_default=sa.text("true")),
            sa.Column("is_superadmin", sa.Boolean, nullable=True, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    if "user_tenant_memberships" not in tables:
        op.create_table(
            "user_tenant_memberships",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
        )
        op.create_index("ix_utm_user_id", "user_tenant_memberships", ["user_id"])
        op.create_index("ix_utm_tenant_id", "user_tenant_memberships", ["tenant_id"])


def downgrade() -> None:
    insp = _inspector()
    tables = insp.get_table_names()
    if "user_tenant_memberships" in tables:
        op.drop_table("user_tenant_memberships")
    if "users" in tables:
        op.drop_index("ix_users_username", table_name="users")
        op.drop_table("users")
