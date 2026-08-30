"""add pinned flag to node_group_members

Revision ID: 9f1c2d3e4b5a
Revises: a3c1d2e4f5b6
Create Date: 2026-08-30 00:00:00.000000

Adds a ``pinned`` boolean to ``node_group_members`` so a node pinned within a
group is always tried first (independently ranked). Defaults to ``false``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f1c2d3e4b5a"
down_revision: str | Sequence[str] | None = "a3c1d2e4f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    cols = _columns(conn, "node_group_members")
    if "pinned" not in cols:
        with op.batch_alter_table("node_group_members", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "pinned",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                )
            )


def downgrade() -> None:
    conn = op.get_bind()
    cols = _columns(conn, "node_group_members")
    if "pinned" in cols:
        with op.batch_alter_table("node_group_members", schema=None) as batch_op:
            batch_op.drop_column("pinned")
