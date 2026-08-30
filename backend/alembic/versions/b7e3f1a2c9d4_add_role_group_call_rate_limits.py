"""add per-role-group call rate limit columns

Revision ID: b7e3f1a2c9d4
Revises: 9f1c2d3e4b5a
Create Date: 2026-08-30 00:00:00.000000

The global ``call_rate_limit_*`` settings were replaced by per-role-group
limits: every group stores its own sliding-window budget for the
OpenAI/Anthropic gateway endpoints. Custom groups default to 30 requests per
30s; the built-in moderator group is bumped to 50 per 30s here (its seeded
default going forward).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from voidswitch.constants import (
    CALL_RATE_LIMIT_MAX_REQUESTS,
    CALL_RATE_LIMIT_WINDOW_SECONDS,
    MODERATOR_CALL_RATE_LIMIT_MAX_REQUESTS,
)

# revision identifiers, used by Alembic.
revision: str = "b7e3f1a2c9d4"
down_revision: str | Sequence[str] | None = "9f1c2d3e4b5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    cols = _columns(conn, "role_groups")
    if "call_rate_limit_window_seconds" not in cols:
        with op.batch_alter_table("role_groups", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "call_rate_limit_window_seconds",
                    sa.Integer(),
                    nullable=False,
                    server_default=str(CALL_RATE_LIMIT_WINDOW_SECONDS),
                )
            )
            batch_op.add_column(
                sa.Column(
                    "call_rate_limit_max_requests",
                    sa.Integer(),
                    nullable=False,
                    server_default=str(CALL_RATE_LIMIT_MAX_REQUESTS),
                )
            )
    # Existing built-in moderator groups were created before per-group limits
    # existed; the column default (30) is below the moderator default (50).
    role_groups = sa.table(
        "role_groups",
        sa.column("builtin", sa.Boolean()),
        sa.column("call_rate_limit_max_requests", sa.Integer()),
    )
    conn.execute(
        sa.update(role_groups)
        .where(role_groups.c.builtin == sa.true())
        .values(call_rate_limit_max_requests=MODERATOR_CALL_RATE_LIMIT_MAX_REQUESTS)
    )


def downgrade() -> None:
    conn = op.get_bind()
    cols = _columns(conn, "role_groups")
    if "call_rate_limit_window_seconds" in cols:
        with op.batch_alter_table("role_groups", schema=None) as batch_op:
            batch_op.drop_column("call_rate_limit_window_seconds")
            batch_op.drop_column("call_rate_limit_max_requests")
