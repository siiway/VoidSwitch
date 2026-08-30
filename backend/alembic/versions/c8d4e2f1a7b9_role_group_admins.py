"""role group admins: grants column + adminships table

Revision ID: c8d4e2f1a7b9
Revises: b7e3f1a2c9d4
Create Date: 2026-08-31 00:00:00.000000

Adds the "admin" mapping type to role groups. A single mapping row now carries
a ``grants`` field: ``"member"`` (the existing meaning — model call access) or
``"admin"`` (a new read-only observer capability, see ``RoleGroupAdminship``).

Existing rows are backfilled to ``grants="member"`` so behaviour is unchanged
for callers who don't touch the new field. The old uniqueness constraint
``(role_group_id, team_id, min_role)`` is replaced with one that includes
``grants`` so member and admin mappings for the same team+min_role can coexist.

The parallel ``role_group_adminships`` table stores the resolved adminships
(recomputed at every login from ``grants="admin"`` mappings, mirroring the
existing ``role_group_memberships`` design). ``source`` is kept for parity with
memberships so a future "manual" assignment path is a no-migration change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d4e2f1a7b9"
down_revision: str | Sequence[str] | None = "b7e3f1a2c9d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def _tables(conn) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return set(sa_inspect(conn).get_table_names())


def _unique_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {uc["name"] for uc in sa_inspect(conn).get_unique_constraints(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # 1) role_group_mappings: add ``grants`` column, default "member". Existing
    #    rows are backfilled by the server_default. Drop the old uniqueness
    #    constraint and add a new one including grants.
    cols = _columns(conn, "role_group_mappings")
    if "grants" not in cols:
        with op.batch_alter_table("role_group_mappings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "grants",
                    sa.String(length=16),
                    nullable=False,
                    server_default="member",
                )
            )

    existing = _unique_names(conn, "role_group_mappings")
    with op.batch_alter_table("role_group_mappings", schema=None) as batch_op:
        if "uq_group_team_role" in existing:
            batch_op.drop_constraint("uq_group_team_role", type_="unique")
        if "uq_group_team_role_grants" not in existing:
            batch_op.create_unique_constraint(
                "uq_group_team_role_grants",
                ["role_group_id", "team_id", "min_role", "grants"],
            )

    # 2) role_group_adminships: new table (parallel to role_group_memberships).
    if "role_group_adminships" not in _tables(conn):
        op.create_table(
            "role_group_adminships",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role_group_id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="auto"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["role_group_id"], ["role_groups.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "role_group_id", name="uq_user_group_admin"),
        )
        op.create_index(
            "ix_role_group_adminships_user_id",
            "role_group_adminships",
            ["user_id"],
        )
        op.create_index(
            "ix_role_group_adminships_role_group_id",
            "role_group_adminships",
            ["role_group_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "role_group_adminships" in _tables(conn):
        op.drop_index("ix_role_group_adminships_role_group_id", table_name="role_group_adminships")
        op.drop_index("ix_role_group_adminships_user_id", table_name="role_group_adminships")
        op.drop_table("role_group_adminships")

    existing = _unique_names(conn, "role_group_mappings")
    with op.batch_alter_table("role_group_mappings", schema=None) as batch_op:
        if "uq_group_team_role_grants" in existing:
            batch_op.drop_constraint("uq_group_team_role_grants", type_="unique")
        if "uq_group_team_role" not in existing:
            batch_op.create_unique_constraint(
                "uq_group_team_role", ["role_group_id", "team_id", "min_role"]
            )
    cols = _columns(conn, "role_group_mappings")
    if "grants" in cols:
        with op.batch_alter_table("role_group_mappings", schema=None) as batch_op:
            batch_op.drop_column("grants")
