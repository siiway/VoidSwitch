"""add passthrough fields to provider, model categories, category_id on exposed_models

Revision ID: 58e48e546df2
Revises: 6151bc02069f
Create Date: 2026-08-28 20:22:56.513967

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "58e48e546df2"
down_revision: str | Sequence[str] | None = "6151bc02069f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(conn, name: str) -> bool:
    from sqlalchemy import inspect as sa_inspect

    return name in set(sa_inspect(conn).get_table_names())


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------- #
    # 1. model_categories — new table (idempotent)
    # ------------------------------------------------------------------- #
    if not _has_table(conn, "model_categories"):
        op.create_table(
            "model_categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_model_categories_slug", "model_categories", ["slug"], unique=True)

    # ------------------------------------------------------------------- #
    # 2. exposed_models — add category_id FK (idempotent)
    # ------------------------------------------------------------------- #
    em_cols = _columns(conn, "exposed_models")
    if "category_id" not in em_cols:
        with op.batch_alter_table("exposed_models", schema=None) as batch_op:
            batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
            batch_op.create_index(
                batch_op.f("ix_exposed_models_category_id"), ["category_id"], unique=False
            )
            batch_op.create_foreign_key(
                "fk_exposed_models_category_id",
                "model_categories",
                ["category_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ------------------------------------------------------------------- #
    # 3. providers — add passthrough_enabled + passthrough_models (idempotent)
    # ------------------------------------------------------------------- #
    p_cols = _columns(conn, "providers")
    if "passthrough_enabled" not in p_cols or "passthrough_models" not in p_cols:
        with op.batch_alter_table("providers", schema=None) as batch_op:
            if "passthrough_enabled" not in p_cols:
                batch_op.add_column(
                    sa.Column(
                        "passthrough_enabled",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false"),
                    )
                )
            if "passthrough_models" not in p_cols:
                batch_op.add_column(
                    sa.Column(
                        "passthrough_models",
                        sa.JSON(),
                        nullable=False,
                        server_default="[]",
                    )
                )


def downgrade() -> None:
    conn = op.get_bind()

    p_cols = _columns(conn, "providers")
    if "passthrough_models" in p_cols or "passthrough_enabled" in p_cols:
        with op.batch_alter_table("providers", schema=None) as batch_op:
            if "passthrough_models" in p_cols:
                batch_op.drop_column("passthrough_models")
            if "passthrough_enabled" in p_cols:
                batch_op.drop_column("passthrough_enabled")

    em_cols = _columns(conn, "exposed_models")
    if "category_id" in em_cols:
        with op.batch_alter_table("exposed_models", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_exposed_models_category_id"))
            batch_op.drop_column("category_id")

    if _has_table(conn, "model_categories"):
        op.drop_index("ix_model_categories_slug", table_name="model_categories")
        op.drop_table("model_categories")
