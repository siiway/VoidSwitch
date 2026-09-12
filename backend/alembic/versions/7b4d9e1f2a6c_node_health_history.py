"""add node health sample history

Revision ID: 7b4d9e1f2a6c
Revises: f6a3b8c2d1e4
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b4d9e1f2a6c"
down_revision: str | Sequence[str] | None = "f6a3b8c2d1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "node_health_samples" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "node_health_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(16), nullable=False, server_default="request"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("status_code", sa.Integer()),
        sa.Column("error", sa.String(255)),
    )
    op.create_index("ix_node_health_samples_node_id", "node_health_samples", ["node_id"])
    op.create_index("ix_node_health_samples_ts", "node_health_samples", ["ts"])
    op.create_index("ix_node_health_samples_node_ts", "node_health_samples", ["node_id", "ts"])


def downgrade() -> None:
    op.drop_table("node_health_samples")
