"""sync missing indexes and constraints

Revision ID: 53a283f6e778
Revises: e1f2a3b4c5d6
Create Date: 2026-10-04 20:43:04.463739

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "53a283f6e778"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    prov_indexes = {ix["name"] for ix in insp.get_indexes("providers")}
    with op.batch_alter_table("providers", schema=None) as batch_op:
        batch_op.alter_column(
            "uuid",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        if "ix_providers_uuid" not in prov_indexes:
            batch_op.create_index(batch_op.f("ix_providers_uuid"), ["uuid"], unique=True)
        if "ix_providers_key_api_token_hash" not in prov_indexes:
            batch_op.create_index(
                batch_op.f("ix_providers_key_api_token_hash"),
                ["key_api_token_hash"],
                unique=True,
            )
        batch_op.create_foreign_key(
            "fk_providers_node_group_id",
            "node_groups",
            ["node_group_id"],
            ["id"],
            ondelete="SET NULL",
        )

    req_indexes = {ix["name"] for ix in insp.get_indexes("request_logs")}
    with op.batch_alter_table("request_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.Numeric(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "finished_at",
            existing_type=sa.Numeric(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        if "ix_request_logs_debug" not in req_indexes:
            batch_op.create_index(batch_op.f("ix_request_logs_debug"), ["debug"], unique=False)
        if "ix_request_logs_req_status" not in req_indexes:
            batch_op.create_index(
                batch_op.f("ix_request_logs_req_status"), ["req_status"], unique=False
            )
        if "ix_request_logs_session_id" not in req_indexes:
            batch_op.create_index(
                batch_op.f("ix_request_logs_session_id"), ["session_id"], unique=False
            )

    user_indexes = {ix["name"] for ix in insp.get_indexes("users")}
    if "ix_users_login_token_hash" not in user_indexes:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_users_login_token_hash"), ["login_token_hash"], unique=True
            )

    token_indexes = {ix["name"] for ix in insp.get_indexes("void_tokens")}
    if "ix_void_tokens_deleted" not in token_indexes:
        with op.batch_alter_table("void_tokens", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_void_tokens_deleted"), ["deleted"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("void_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_void_tokens_deleted"))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_login_token_hash"))

    with op.batch_alter_table("request_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_request_logs_session_id"))
        batch_op.drop_index(batch_op.f("ix_request_logs_req_status"))
        batch_op.drop_index(batch_op.f("ix_request_logs_debug"))
        batch_op.alter_column(
            "finished_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.Numeric(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.Numeric(),
            existing_nullable=True,
        )

    with op.batch_alter_table("providers", schema=None) as batch_op:
        batch_op.drop_constraint("fk_providers_node_group_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_providers_key_api_token_hash"))
        batch_op.drop_index(batch_op.f("ix_providers_uuid"))
        batch_op.alter_column(
            "uuid",
            existing_type=sa.String(length=36),
            nullable=True,
        )
