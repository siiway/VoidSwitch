"""add ordered route upstream groups

Revision ID: e1f2a3b4c5d6
Revises: d9a4c7e2b1f6
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d9a4c7e2b1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("route_upstreams")
    }
    if "group_position" not in columns:
        with op.batch_alter_table("route_upstreams") as batch_op:
            batch_op.add_column(
                sa.Column("group_position", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.drop_constraint("uq_route_upstream", type_="unique")
            batch_op.create_unique_constraint(
                "uq_route_upstream",
                ["route_id", "group_position", "provider_id", "upstream_model", "key_pool"],
            )


def downgrade() -> None:
    with op.batch_alter_table("route_upstreams") as batch_op:
        batch_op.drop_constraint("uq_route_upstream", type_="unique")
        batch_op.drop_column("group_position")
        batch_op.create_unique_constraint(
            "uq_route_upstream", ["route_id", "provider_id", "upstream_model", "key_pool"]
        )
