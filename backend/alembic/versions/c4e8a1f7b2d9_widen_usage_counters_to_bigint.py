"""widen usage counters to bigint

Revision ID: c4e8a1f7b2d9
Revises: 53a283f6e778
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1f7b2d9"
down_revision: str | Sequence[str] | None = "53a283f6e778"
branch_labels = None
depends_on = None

_COLUMNS = {
    "void_tokens": ("total_requests", "total_tokens"),
    "api_keys": ("total_requests",),
    "request_logs": ("prompt_tokens", "completion_tokens", "total_tokens"),
    "usage_daily": ("tokens", "requests"),
    "session_spans": ("requests",),
}


def upgrade() -> None:
    for table, columns in _COLUMNS.items():
        with op.batch_alter_table(table) as batch_op:
            for column in columns:
                batch_op.alter_column(
                    column,
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=False,
                )


def downgrade() -> None:
    for table, columns in _COLUMNS.items():
        with op.batch_alter_table(table) as batch_op:
            for column in columns:
                batch_op.alter_column(
                    column,
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False,
                )
