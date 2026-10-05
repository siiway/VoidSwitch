"""sync missing indexes and constraints

Revision ID: 53a283f6e778
Revises: e1f2a3b4c5d6
Create Date: 2026-10-04 20:43:04.463739

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    dialect = conn.dialect.name
    # Older schemas stored these as Unix epoch seconds, while some installations
    # already have timestamp columns. Inspect the live schema before choosing a
    # PostgreSQL conversion: to_timestamp() only accepts numeric epoch values.
    request_log_columns = {column["name"]: column for column in insp.get_columns("request_logs")}
    started_is_datetime = isinstance(request_log_columns["started_at"]["type"], sa.DateTime)
    finished_is_datetime = isinstance(request_log_columns["finished_at"]["type"], sa.DateTime)
    if dialect == "sqlite" and not started_is_datetime:
        conn.execute(
            sa.text(
                "UPDATE request_logs SET started_at = "
                "strftime('%Y-%m-%d %H:%M:%f', started_at, 'unixepoch') "
                "WHERE started_at IS NOT NULL"
            )
        )
    if dialect == "sqlite" and not finished_is_datetime:
        conn.execute(
            sa.text(
                "UPDATE request_logs SET finished_at = "
                "strftime('%Y-%m-%d %H:%M:%f', finished_at, 'unixepoch') "
                "WHERE finished_at IS NOT NULL"
            )
        )

    def timestamp_type_args(column_name: str) -> dict[str, Any]:
        if dialect != "postgresql":
            return {}
        current_type = request_log_columns[column_name]["type"]
        using = (
            column_name if isinstance(current_type, sa.DateTime) else f"to_timestamp({column_name})"
        )
        return {"postgresql_using": using}

    started_type_args = timestamp_type_args("started_at")
    finished_type_args = timestamp_type_args("finished_at")
    with op.batch_alter_table("request_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.Numeric(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            **started_type_args,
        )
        batch_op.alter_column(
            "finished_at",
            existing_type=sa.Numeric(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            **finished_type_args,
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
    conn = op.get_bind()
    insp = sa.inspect(conn)
    token_indexes = {ix["name"] for ix in insp.get_indexes("void_tokens")}
    user_indexes = {ix["name"] for ix in insp.get_indexes("users")}
    req_indexes = {ix["name"] for ix in insp.get_indexes("request_logs")}
    provider_indexes = {ix["name"] for ix in insp.get_indexes("providers")}

    if "ix_void_tokens_deleted" in token_indexes:
        with op.batch_alter_table("void_tokens", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_void_tokens_deleted"))

    if "ix_users_login_token_hash" in user_indexes:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_users_login_token_hash"))

    dialect = conn.dialect.name
    request_log_columns = {column["name"]: column for column in insp.get_columns("request_logs")}
    started_is_datetime = isinstance(request_log_columns["started_at"]["type"], sa.DateTime)
    finished_is_datetime = isinstance(request_log_columns["finished_at"]["type"], sa.DateTime)
    if dialect == "sqlite" and started_is_datetime:
        conn.execute(
            sa.text(
                "UPDATE request_logs SET started_at = "
                "(julianday(started_at) - 2440587.5) * 86400 "
                "WHERE started_at IS NOT NULL"
            )
        )
    if dialect == "sqlite" and finished_is_datetime:
        conn.execute(
            sa.text(
                "UPDATE request_logs SET finished_at = "
                "(julianday(finished_at) - 2440587.5) * 86400 "
                "WHERE finished_at IS NOT NULL"
            )
        )
    finished_epoch_args = (
        {"postgresql_using": "extract(epoch from finished_at)"}
        if dialect == "postgresql" and finished_is_datetime
        else {}
    )
    started_epoch_args = (
        {"postgresql_using": "extract(epoch from started_at)"}
        if dialect == "postgresql" and started_is_datetime
        else {}
    )
    with op.batch_alter_table("request_logs", schema=None) as batch_op:
        if "ix_request_logs_session_id" in req_indexes:
            batch_op.drop_index(batch_op.f("ix_request_logs_session_id"))
        if "ix_request_logs_req_status" in req_indexes:
            batch_op.drop_index(batch_op.f("ix_request_logs_req_status"))
        if "ix_request_logs_debug" in req_indexes:
            batch_op.drop_index(batch_op.f("ix_request_logs_debug"))
        batch_op.alter_column(
            "finished_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.Numeric(),
            existing_nullable=True,
            **finished_epoch_args,
        )
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.Numeric(),
            existing_nullable=True,
            **started_epoch_args,
        )

    with op.batch_alter_table("providers", schema=None) as batch_op:
        batch_op.drop_constraint("fk_providers_node_group_id", type_="foreignkey")
        if "ix_providers_key_api_token_hash" in provider_indexes:
            batch_op.drop_index(batch_op.f("ix_providers_key_api_token_hash"))
        if "ix_providers_uuid" in provider_indexes:
            batch_op.drop_index(batch_op.f("ix_providers_uuid"))
        batch_op.alter_column(
            "uuid",
            existing_type=sa.String(length=36),
            nullable=True,
        )
