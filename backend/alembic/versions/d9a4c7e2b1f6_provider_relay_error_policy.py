"""add provider relay error policy

Revision ID: d9a4c7e2b1f6
Revises: 7b4d9e1f2a6c
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9a4c7e2b1f6"
down_revision: str | Sequence[str] | None = "7b4d9e1f2a6c"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("providers")}


def _request_log_columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("request_logs")}


def upgrade() -> None:
    columns = _columns()
    with op.batch_alter_table("providers") as batch_op:
        if "new_api_mode" not in columns:
            batch_op.add_column(
                sa.Column("new_api_mode", sa.String(16), nullable=False, server_default="auto")
            )
        if "protected_error_retry_enabled" not in columns:
            batch_op.add_column(
                sa.Column(
                    "protected_error_retry_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "selective_ignore_rules" not in columns:
            batch_op.add_column(
                sa.Column("selective_ignore_rules", sa.JSON(), nullable=False, server_default="[]")
            )
    log_columns = _request_log_columns()
    with op.batch_alter_table("request_logs") as batch_op:
        if "provider_attempts" not in log_columns:
            batch_op.add_column(
                sa.Column("provider_attempts", sa.Integer(), nullable=False, server_default="1")
            )
        if "network_attempts" not in log_columns:
            batch_op.add_column(
                sa.Column("network_attempts", sa.Integer(), nullable=False, server_default="1")
            )

    settings = sa.table(
        "settings",
        sa.column("key", sa.String()),
        sa.column("value", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    request_logs = sa.table(
        "request_logs",
        sa.column("attempts", sa.Integer()),
        sa.column("network_attempts", sa.Integer()),
    )
    bind = op.get_bind()
    bind.execute(
        request_logs.update().values(network_attempts=sa.func.coalesce(request_logs.c.attempts, 1))
    )
    old = bind.execute(sa.select(settings.c.value).where(settings.c.key == "max_retries")).scalar()
    exists = bind.execute(
        sa.select(settings.c.key).where(settings.c.key == "max_provider_attempts")
    ).scalar()
    if exists is None and old is not None:
        bind.execute(
            settings.insert().values(
                key="max_provider_attempts", value=old, updated_at=sa.func.now()
            )
        )
    bind.execute(settings.delete().where(settings.c.key == "max_retries"))


def downgrade() -> None:
    settings = sa.table(
        "settings",
        sa.column("key", sa.String()),
        sa.column("value", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    value = bind.execute(
        sa.select(settings.c.value).where(settings.c.key == "max_provider_attempts")
    ).scalar()
    exists = bind.execute(sa.select(settings.c.key).where(settings.c.key == "max_retries")).scalar()
    if exists is None and value is not None:
        bind.execute(
            settings.insert().values(key="max_retries", value=value, updated_at=sa.func.now())
        )
    bind.execute(settings.delete().where(settings.c.key == "max_provider_attempts"))
    log_columns = _request_log_columns()
    with op.batch_alter_table("request_logs") as batch_op:
        if "network_attempts" in log_columns:
            batch_op.drop_column("network_attempts")
        if "provider_attempts" in log_columns:
            batch_op.drop_column("provider_attempts")
    columns = _columns()
    with op.batch_alter_table("providers") as batch_op:
        if "selective_ignore_rules" in columns:
            batch_op.drop_column("selective_ignore_rules")
        if "protected_error_retry_enabled" in columns:
            batch_op.drop_column("protected_error_retry_enabled")
        if "new_api_mode" in columns:
            batch_op.drop_column("new_api_mode")
