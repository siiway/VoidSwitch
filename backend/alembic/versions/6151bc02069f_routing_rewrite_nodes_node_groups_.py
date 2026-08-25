"""routing rewrite: nodes, node groups, exposed models, routes

Revision ID: 6151bc02069f
Revises: 0001_baseline

Creates the outbound routing system (nodes + node groups, replacing providers'
flat ``proxy_mode``/``proxy_ids``) and the model routing system (exposed models
+ route flowcharts, replacing the old provider-served catalog). Existing data is
migrated to preserve behaviour:

* every ``proxies`` row → a ``nodes`` row, collected into a seeded ``default``
  set, plus an empty ``system`` group (both idempotent);
* every provider gets a unique ``slug`` (derived from its name);
* every ``models`` (ModelEntry) row → an ``exposed_models`` row with a 1:1
  passthrough route (one layer, one weighted entry per serving provider).

The tables are created idempotently (guarded by existence checks), so this is
safe on a fresh database and on an existing production install.

Postgres notes: this migration is SQLite- and PostgreSQL-correct. Booleans are
bound as ``TRUE``/``FALSE`` (never ``0``/``1``), inserted ids come back via
``RETURNING id`` (never ``cursor.lastrowid``, which Postgres leaves unset), and
the ``slug`` unique index is created only after the per-provider slugs are
backfilled (otherwise all existing providers would share ``''`` and violate the
index).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6151bc02069f"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fallback timestamp for legacy rows missing created_at/updated_at. Bound as a
# real datetime (never a string): asyncpg rejects string binds for DateTime
# columns, and the whole migration must be portable across SQLite (aiosqlite)
# and Postgres (asyncpg/psycopg).
_FALLBACK_TS = dt.datetime(2026, 8, 17, tzinfo=dt.UTC)


def _has_table(conn, name: str) -> bool:
    from sqlalchemy import inspect as sa_inspect

    return name in set(sa_inspect(conn).get_table_names())


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------ #
    # 1. New tables (idempotent — same shape as Base.metadata)
    # ------------------------------------------------------------------ #
    if not _has_table(conn, "nodes"):
        op.create_table(
            "nodes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("type", sa.String(length=16), nullable=False, server_default="http"),
            sa.Column("token_ciphertext", sa.Text(), nullable=True),
            sa.Column("local_address", sa.String(length=64), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("latency_ewma", sa.Float(), nullable=True),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("disabled_reason", sa.String(length=255), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("url", name="uq_nodes_url"),
        )
        op.create_index("ix_nodes_enabled_status", "nodes", ["enabled", "status"])
    else:
        cols = _columns(conn, "nodes")
        if "latency_ewma" not in cols:
            op.add_column("nodes", sa.Column("latency_ewma", sa.Float(), nullable=True))

    if not _has_table(conn, "node_groups"):
        op.create_table(
            "node_groups",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("slug", sa.String(length=64), nullable=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("probe_url", sa.String(length=512), nullable=True),
            sa.Column("probe_interval_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("name", name="uq_node_groups_name"),
        )
        op.create_index("ix_node_groups_slug", "node_groups", ["slug"], unique=True)

    if not _has_table(conn, "node_group_members"):
        op.create_table(
            "node_group_members",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.Integer(), nullable=True),
            sa.Column("source_group_id", sa.Integer(), nullable=True),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("group_id", "node_id", name="uq_group_node"),
            sa.UniqueConstraint("group_id", "source_group_id", name="uq_group_source_group"),
            sa.ForeignKeyConstraint(["group_id"], ["node_groups.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_group_id"], ["node_groups.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_node_group_members_group_id", "node_group_members", ["group_id"])
        op.create_index("ix_node_group_members_node_id", "node_group_members", ["node_id"])
        op.create_index(
            "ix_node_group_members_source_group_id", "node_group_members", ["source_group_id"]
        )

    if not _has_table(conn, "exposed_models"):
        op.create_table(
            "exposed_models",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("model_id", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("opencode_config", sa.JSON(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("allowed_role_group_ids", sa.JSON(), nullable=True),
            sa.Column("limit_context", sa.Integer(), nullable=True),
            sa.Column("limit_input", sa.Integer(), nullable=True),
            sa.Column("limit_output", sa.Integer(), nullable=True),
            sa.Column("reasoning", sa.Boolean(), nullable=True),
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("modalities", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("models_dev_id", sa.String(length=255), nullable=True),
            sa.Column("models_dev_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("added_by", sa.Integer(), nullable=True),
            sa.Column("added_by_name", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("model_id", name="uq_exposed_models_model_id"),
        )
        op.create_index("ix_exposed_models_model_id", "exposed_models", ["model_id"], unique=True)

    if not _has_table(conn, "routes"):
        op.create_table(
            "routes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("exposed_model_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["exposed_model_id"], ["exposed_models.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("exposed_model_id", name="uq_routes_exposed_model_id"),
        )
        op.create_index("ix_routes_exposed_model_id", "routes", ["exposed_model_id"])

    if not _has_table(conn, "route_layers"):
        op.create_table(
            "route_layers",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("route_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_route_layers_route_id", "route_layers", ["route_id"])

    if not _has_table(conn, "route_pool_entries"):
        op.create_table(
            "route_pool_entries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("layer_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("upstream_model", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("key_pool", sa.String(length=64), nullable=False, server_default=""),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["layer_id"], ["route_layers.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_route_pool_entries_layer_id", "route_pool_entries", ["layer_id"])

    if not _has_table(conn, "models_dev_cache"):
        op.create_table(
            "models_dev_cache",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    # ------------------------------------------------------------------ #
    # 2. Provider new columns (slug, node_group_id)
    # ------------------------------------------------------------------ #
    pcols = _columns(conn, "providers")
    if "slug" not in pcols:
        op.add_column(
            "providers",
            sa.Column("slug", sa.String(length=120), nullable=False, server_default=""),
        )
    if "node_group_id" not in pcols:
        op.add_column(
            "providers",
            sa.Column("node_group_id", sa.Integer(), nullable=True),
        )

    # ------------------------------------------------------------------ #
    # 3. Seed default + system node groups (idempotent)
    # ------------------------------------------------------------------ #
    conn.execute(
        sa.text(
            "INSERT INTO node_groups (slug, name, is_system, probe_interval_seconds, "
            "created_at, updated_at) "
            "SELECT 'default', 'Default', FALSE, 0, :now, :now "
            "WHERE NOT EXISTS (SELECT 1 FROM node_groups WHERE slug = 'default')"
        ),
        {"now": _FALLBACK_TS},
    )
    conn.execute(
        sa.text(
            "INSERT INTO node_groups (slug, name, is_system, probe_interval_seconds, "
            "created_at, updated_at) "
            "SELECT 'system', 'System', TRUE, 0, :now, :now "
            "WHERE NOT EXISTS (SELECT 1 FROM node_groups WHERE slug = 'system')"
        ),
        {"now": _FALLBACK_TS},
    )

    # ------------------------------------------------------------------ #
    # 4. Migrate proxies → nodes, all into the default group
    # ------------------------------------------------------------------ #
    if _has_table(conn, "proxies"):
        default_id = conn.execute(
            sa.text("SELECT id FROM node_groups WHERE slug = 'default'")
        ).scalar()
        if default_id is not None:
            rows = conn.execute(
                sa.text(
                    "SELECT id, url, local_address, enabled, status, failed_count, "
                    "weight, latency_ms, note, disabled_reason, last_used_at, "
                    "last_checked_at, created_at, updated_at FROM proxies"
                )
            ).fetchall()
            for r in rows:
                _id, url, local, enabled, status, failed, weight, lat, note, reason, lu, lc, ca, ua = r
                new_id = conn.execute(
                    sa.text(
                        "INSERT INTO nodes (url, type, local_address, enabled, status, "
                        "failed_count, weight, latency_ms, note, disabled_reason, "
                        "last_used_at, last_checked_at, created_at, updated_at) "
                        "VALUES (:url, 'http', :local, :enabled, :status, :failed, "
                        ":weight, :lat, :note, :reason, :lu, :lc, :ca, :ua) "
                        "RETURNING id"
                    ),
                    {
                        "url": url or "",
                        "local": local,
                        "enabled": bool(enabled),
                        "status": status or "active",
                        "failed": failed or 0,
                        "weight": weight or 1,
                        "lat": lat,
                        "note": note,
                        "reason": reason,
                        "lu": lu,
                        "lc": lc,
                        "ca": ca or _FALLBACK_TS,
                        "ua": ua or _FALLBACK_TS,
                    },
                ).scalar_one()
                conn.execute(
                    sa.text(
                        "INSERT INTO node_group_members (group_id, node_id, weight) "
                        "VALUES (:g, :n, 1)"
                    ),
                    {"g": default_id, "n": new_id},
                )

    # ------------------------------------------------------------------ #
    # 5. Provider slugs (idempotent — backfill where empty, then unique index)
    # ------------------------------------------------------------------ #
    provs = conn.execute(
        sa.text(
            "SELECT id, name, slug FROM providers WHERE slug IS NULL OR slug = ''"
        )
    ).fetchall()
    used: set[str] = set(
        s
        for (s,) in conn.execute(
            sa.text("SELECT slug FROM providers WHERE slug IS NOT NULL AND slug != ''")
        ).fetchall()
    )

    def _slug(name: str) -> str:
        out: list[str] = []
        for ch in (name or "").lower():
            if ch.isalnum():
                out.append(ch)
            elif out and out[-1] != "-":
                out.append("-")
        return "".join(out).strip("-") or "provider"

    for pid, name, _slugcol in provs:
        base = _slug(name)
        cand = base
        n = 2
        while cand in used:
            cand = f"{base}-{n}"
            n += 1
        used.add(cand)
        conn.execute(
            sa.text("UPDATE providers SET slug = :s WHERE id = :i"),
            {"s": cand[:64], "i": pid},
        )

    # Unique index only now — every provider has a distinct slug.
    existing_indexes = {i["name"] for i in conn.dialect.get_indexes(conn, "providers")}
    if "ix_providers_slug" not in existing_indexes:
        op.create_index("ix_providers_slug", "providers", ["slug"], unique=True)
    if "ix_providers_node_group_id" not in existing_indexes:
        op.create_index("ix_providers_node_group_id", "providers", ["node_group_id"])

    # ------------------------------------------------------------------ #
    # 6. Migrate models (ModelEntry) → exposed_models + 1:1 route
    # ------------------------------------------------------------------ #
    if _has_table(conn, "models"):
        entry_rows = conn.execute(
            sa.text(
                "SELECT id, model_id, display_name, description, opencode_config, "
                "enabled, allowed_role_group_ids, added_by, added_by_name, "
                "created_at, updated_at FROM models"
            )
        ).fetchall()
        for r in entry_rows:
            _id, model_id, disp, desc, ocfg, enabled, allowed, added_by, added_by_name, ca, ua = r
            exposed_id = conn.execute(
                sa.text(
                    "INSERT INTO exposed_models (model_id, display_name, description, "
                    "opencode_config, enabled, allowed_role_group_ids, capabilities, "
                    "modalities, added_by, added_by_name, created_at, updated_at) "
                    "VALUES (:m, :d, :desc, :ocfg, :e, :a, '{}', '{}', :ab, :abn, :ca, :ua) "
                    "RETURNING id"
                ),
                {
                    "m": model_id,
                    "d": disp,
                    "desc": desc,
                    # JSONB comes back as a Python dict/list; a raw text() bind
                    # can't adapt it, so serialise to a JSON string (Postgres
                    # casts text → jsonb, SQLite stores the text).
                    "ocfg": json.dumps(ocfg) if ocfg is not None else "{}",
                    "e": bool(enabled),
                    "a": json.dumps(allowed) if allowed is not None else "[]",
                    "ab": added_by,
                    "abn": added_by_name,
                    "ca": ca or _FALLBACK_TS,
                    "ua": ua or _FALLBACK_TS,
                },
            ).scalar_one()
            route_id = conn.execute(
                sa.text(
                    "INSERT INTO routes (exposed_model_id, created_at, updated_at) "
                    "VALUES (:e, :now, :now) RETURNING id"
                ),
                {"e": exposed_id, "now": _FALLBACK_TS},
            ).scalar_one()
            layer_id = conn.execute(
                sa.text(
                    "INSERT INTO route_layers (route_id, position, max_attempts) "
                    "VALUES (:r, 0, 1) RETURNING id"
                ),
                {"r": route_id},
            ).scalar_one()
            # One weighted entry per serving provider.
            servs = conn.execute(
                sa.text(
                    "SELECT id, name, weight, models FROM providers WHERE enabled"
                )
            ).fetchall()
            from fnmatch import fnmatch

            for pid, _pname, pweight, models_json in servs:
                patterns = models_json or []
                if not any(
                    p == "*" or p == model_id or (isinstance(p, str) and fnmatch(model_id, p))
                    for p in patterns
                ):
                    continue
                conn.execute(
                    sa.text(
                        "INSERT INTO route_pool_entries (layer_id, provider_id, "
                        "upstream_model, weight, enabled, key_pool) "
                        "VALUES (:l, :p, :um, :w, TRUE, '')"
                    ),
                    {"l": layer_id, "p": pid, "um": model_id, "w": max(1, pweight or 1)},
                )

    # ------------------------------------------------------------------ #
    # 7. Drop the old provider proxy columns (guarded — fresh DBs lack them)
    # ------------------------------------------------------------------ #
    pcols = _columns(conn, "providers")
    with op.batch_alter_table("providers", schema=None) as batch_op:
        if "proxy_mode" in pcols:
            batch_op.drop_column("proxy_mode")
        if "proxy_ids" in pcols:
            batch_op.drop_column("proxy_ids")


def downgrade() -> None:
    """Best-effort reverse: restore providers' proxy columns and drop the new
    tables. Data loss is inherent on downgrade (no reverse mapping exists)."""
    conn = op.get_bind()
    pcols = _columns(conn, "providers")
    with op.batch_alter_table("providers", schema=None) as batch_op:
        if "proxy_mode" not in pcols:
            batch_op.add_column(
                sa.Column("proxy_mode", sa.String(length=16), server_default="all", nullable=False)
            )
        if "proxy_ids" not in pcols:
            batch_op.add_column(
                sa.Column("proxy_ids", sa.JSON(), server_default="[]", nullable=False)
            )
    op.drop_table("models_dev_cache")
    op.drop_table("route_pool_entries")
    op.drop_table("route_layers")
    op.drop_table("routes")
    op.drop_table("exposed_models")
    op.drop_table("node_group_members")
    op.drop_table("node_groups")
    op.drop_table("nodes")