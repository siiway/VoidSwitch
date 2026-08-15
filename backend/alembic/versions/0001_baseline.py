"""baseline — current VoidSwitch schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-15

This is the single revision that carries the project into Alembic management. It
deliberately does NOT express a hand-written history of every column ever added:
instead it brings **any** database — a brand-new one or a pre-Alembic install
that was previously maintained by the in-boot ``_ADDED_COLUMNS`` helper — to the
current schema in one idempotent step:

* ``Base.metadata.create_all`` creates any missing *tables* (fresh installs) and
  is a no-op on existing ones;
* the frozen pre-Alembic helpers (``_add_missing_columns`` / ``_ensure_indexes``
  / ``_backfill_provider_uuids``) close any remaining column/index/backfill gaps
  on databases that predate those fields.

After this revision, every schema change must be a new Alembic revision; the
``_ADDED_COLUMNS`` list is frozen and never extended again.
"""

from alembic import op
from sqlalchemy import text

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _heal_pre_alembic() -> None:
    """Close gaps left by the pre-Alembic era on existing databases."""
    from voidswitch.core.database import (
        _add_missing_columns,
        _backfill_provider_uuids,
        _ensure_indexes,
    )
    from voidswitch.models.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    _add_missing_columns(bind)
    _ensure_indexes(bind)
    _backfill_provider_uuids(bind)


def upgrade() -> None:
    # create_all + the healing helpers are idempotent, so this is safe to run on
    # both a fresh database and an existing production install.
    _heal_pre_alembic()


def downgrade() -> None:
    from voidswitch.models.db import Base

    bind = op.get_bind()
    # Drop Alembic's own version marker, then the schema.
    bind.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=bind)
