"""add brand column to exposed_models

Revision ID: a3c1d2e4f5b6
Revises: 58e48e546df2
Create Date: 2026-08-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c1d2e4f5b6"
down_revision: str | Sequence[str] | None = "58e48e546df2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    em_cols = _columns(conn, "exposed_models")
    if "brand" not in em_cols:
        with op.batch_alter_table("exposed_models", schema=None) as batch_op:
            batch_op.add_column(sa.Column("brand", sa.String(length=64), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    em_cols = _columns(conn, "exposed_models")
    if "brand" in em_cols:
        with op.batch_alter_table("exposed_models", schema=None) as batch_op:
            batch_op.drop_column("brand")
