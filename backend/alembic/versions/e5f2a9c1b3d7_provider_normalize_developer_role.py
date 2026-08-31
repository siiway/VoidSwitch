"""providers: gate developer→system remap behind a per-provider flag

Revision ID: e5f2a9c1b3d7
Revises: c8d4e2f1a7b9
Create Date: 2026-08-31 08:00:00.000000

The ``adeddb3`` fix unconditionally rewrote OpenAI-style ``role: "developer"``
messages down to ``role: "system"`` before every OpenAI-style upstream call.
That was correct for the many OpenAI-compatible upstreams that reject the
``developer`` role, but wrong for the (growing) set of upstreams — real OpenAI
included — that do accept it natively and may treat ``developer`` differently
from ``system``.

This migration adds ``providers.normalize_developer_role_to_system`` (default
``true``) so the remap can be turned off per provider without giving up the
safe default. Existing rows are backfilled to ``true`` to preserve the exact
behaviour shipped in ``adeddb3``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f2a9c1b3d7"
down_revision: str | Sequence[str] | None = "c8d4e2f1a7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if "normalize_developer_role_to_system" not in _columns(conn, "providers"):
        with op.batch_alter_table("providers", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "normalize_developer_role_to_system",
                    sa.Boolean(),
                    nullable=False,
                    # Postgres refuses ``DEFAULT 0`` on boolean columns; use the
                    # dialect-agnostic ``true()`` literal.
                    server_default=sa.true(),
                )
            )


def downgrade() -> None:
    conn = op.get_bind()
    if "normalize_developer_role_to_system" in _columns(conn, "providers"):
        with op.batch_alter_table("providers", schema=None) as batch_op:
            batch_op.drop_column("normalize_developer_role_to_system")
