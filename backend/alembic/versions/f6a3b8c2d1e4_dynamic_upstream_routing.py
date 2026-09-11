"""flatten model routes and add dynamic upstream health

Revision ID: f6a3b8c2d1e4
Revises: e5f2a9c1b3d7
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a3b8c2d1e4"
down_revision: str | Sequence[str] | None = "e5f2a9c1b3d7"
branch_labels = None
depends_on = None


def _tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _columns(conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)
    if "route_upstreams" not in tables:
        op.create_table(
            "route_upstreams",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "route_id",
                sa.Integer(),
                sa.ForeignKey("routes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "provider_id",
                sa.Integer(),
                sa.ForeignKey("providers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("upstream_model", sa.String(255), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("key_pool", sa.String(64), nullable=False, server_default=""),
            sa.Column("cooldown_status_codes", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint(
                "route_id", "provider_id", "upstream_model", "key_pool", name="uq_route_upstream"
            ),
        )
        op.create_index("ix_route_upstreams_route_id", "route_upstreams", ["route_id"])
        op.create_index("ix_route_upstreams_provider_id", "route_upstreams", ["provider_id"])
    rows = (
        conn.execute(
            sa.text(
                "SELECT e.provider_id,e.upstream_model,e.weight,e.enabled,e.key_pool,"
                "l.route_id,l.position,e.id FROM route_pool_entries e JOIN route_layers l "
                "ON l.id=e.layer_id ORDER BY l.route_id,l.position,e.id"
            )
        ).fetchall()
        if "route_pool_entries" in tables
        else []
    )
    positions: dict[int, int] = {}
    for row in rows:
        position = positions.get(row.route_id, 0)
        conn.execute(
            sa.text(
                "INSERT INTO route_upstreams(route_id,provider_id,upstream_model,"
                "position,weight,enabled,key_pool,cooldown_status_codes,cooldown_seconds) "
                "VALUES (:r,:p,:m,:o,:w,:e,:k,'[]',0)"
            ),
            {
                "r": row.route_id,
                "p": row.provider_id,
                "m": row.upstream_model,
                "o": position,
                "w": row.weight,
                "e": row.enabled,
                "k": row.key_pool,
            },
        )
        positions[row.route_id] = position + 1
    budgets = (
        conn.execute(
            sa.text(
                "SELECT route_id,SUM(max_attempts) AS budget FROM route_layers GROUP BY route_id"
            )
        ).fetchall()
        if "route_layers" in tables
        else []
    )
    route_columns = _columns(conn, "routes")
    with op.batch_alter_table("routes") as batch:
        if "upstream_select_mode" not in route_columns:
            batch.add_column(
                sa.Column("upstream_select_mode", sa.String(32), nullable=False, server_default="")
            )
        if "upstream_rank_algorithm" not in route_columns:
            batch.add_column(
                sa.Column(
                    "upstream_rank_algorithm", sa.String(32), nullable=False, server_default=""
                )
            )
        if "max_upstream_attempts" not in route_columns:
            batch.add_column(
                sa.Column("max_upstream_attempts", sa.Integer(), nullable=False, server_default="0")
            )
        if "upstream_all_cooled_behavior" not in route_columns:
            batch.add_column(
                sa.Column(
                    "upstream_all_cooled_behavior", sa.String(32), nullable=False, server_default=""
                )
            )
    for row in budgets:
        conn.execute(
            sa.text("UPDATE routes SET max_upstream_attempts=:b WHERE id=:r"),
            {"b": row.budget, "r": row.route_id},
        )
    provider_columns = _columns(conn, "providers")
    with op.batch_alter_table("providers") as batch:
        if "upstream_cooldown_seconds" not in provider_columns:
            batch.add_column(
                sa.Column(
                    "upstream_cooldown_seconds", sa.Integer(), nullable=False, server_default="0"
                )
            )
        if "upstream_cooldown_status_codes" not in provider_columns:
            batch.add_column(
                sa.Column(
                    "upstream_cooldown_status_codes", sa.JSON(), nullable=False, server_default="[]"
                )
            )
        if "upstream_retry_after_headers" not in provider_columns:
            batch.add_column(
                sa.Column(
                    "upstream_retry_after_headers", sa.JSON(), nullable=False, server_default="[]"
                )
            )
        if "upstream_max_keys_per_attempt" not in provider_columns:
            batch.add_column(
                sa.Column(
                    "upstream_max_keys_per_attempt",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
    if "upstream_cooldowns" not in tables:
        op.create_table(
            "upstream_cooldowns",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "provider_id",
                sa.Integer(),
                sa.ForeignKey("providers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("upstream_model", sa.String(255), nullable=False, server_default=""),
            sa.Column("key_pool", sa.String(64), nullable=False, server_default=""),
            sa.Column("until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.String(255)),
            sa.Column("trigger_status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trigger_source", sa.String(32), nullable=False, server_default="global"),
            sa.Column(
                "triggered_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("consecutive_trips", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_success_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "provider_id", "upstream_model", "key_pool", name="uq_upstream_cooldown"
            ),
        )
        op.create_index("ix_upstream_cooldowns_provider_id", "upstream_cooldowns", ["provider_id"])
        op.create_index("ix_upstream_cooldowns_until", "upstream_cooldowns", ["until"])
    if "route_pool_entries" in tables:
        op.drop_table("route_pool_entries")
    if "route_layers" in tables:
        op.drop_table("route_layers")


def downgrade() -> None:
    raise NotImplementedError("Static route layers cannot be reconstructed after flattening")
