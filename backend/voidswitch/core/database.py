"""Async database engine, session factory, and initialisation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# The request-scoped session, set per HTTP request by RequestSessionMiddleware.
_request_session: ContextVar[AsyncSession | None] = ContextVar(
    "voidswitch_request_session", default=None
)

# The request's client context (client IP, user-agent), set alongside the
# session so audit logging can attribute a request even when an individual
# ``record_audit`` call site forgets to pass them.
_request_client: ContextVar[tuple[str | None, str | None] | None] = ContextVar(
    "voidswitch_request_client", default=None
)


def get_request_client() -> tuple[str | None, str | None] | None:
    """The ambient (client IP, user-agent) of the current HTTP request, or
    ``None`` outside a request (background tasks, tests driving the app
    directly)."""
    return _request_client.get()

# Minimal ASGI typing for the middleware.
_Scope = MutableMapping[str, Any]
_Message = MutableMapping[str, Any]
_Receive = Callable[[], Awaitable[_Message]]
_Send = Callable[[_Message], Awaitable[None]]
_ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class Database:
    """Owns an async engine + session factory for a single database URL."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        connect_args: dict[str, object] = {}
        if url.startswith("sqlite"):
            connect_args["timeout"] = 30
        self.engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def create_all(self) -> None:
        from voidswitch.models.db import Base

        async with self.engine.begin() as conn:
            if self.engine.url.get_backend_name() == "sqlite":
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)
            await conn.run_sync(_ensure_indexes)
            await conn.run_sync(_backfill_provider_uuids)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Transactional scope: commit on success, rollback on error."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except asyncio.CancelledError:
                # Cancellation is a BaseException — the except-Exception branch
                # below misses it. Roll back before letting it propagate so the
                # transaction is not left dirty.
                await _safe_rollback(session)
                raise
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()


def _alembic_config() -> Any:
    """Alembic ``Config`` pointing at ``backend/alembic.ini`` (lazy import so the
    dependency is only required when migrations actually run)."""
    from alembic.config import Config as AlembicConfig

    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    return AlembicConfig(str(ini))


async def run_migrations() -> None:
    """Bring the schema up to date (``alembic upgrade head``) in this event loop.

    Runs inside the application's own async engine and passes the open connection
    to ``env.py`` via ``config.attributes["connection"]``, so the migration runs on
    the current loop instead of spawning a fresh one (which would fail from inside
    a running FastAPI lifespan). The first migration (``0001_baseline``) both
    creates a fresh schema and heals pre-Alembic databases, so this is safe on
    every boot.
    """

    db = get_database()
    cfg = _alembic_config()

    async with db.engine.connect() as conn:
        await conn.run_sync(_upgrade_head, cfg)


def _upgrade_head(sync_conn: Any, cfg: Any) -> None:
    from alembic import command

    cfg.attributes["connection"] = sync_conn
    command.upgrade(cfg, "head")


# Columns added to a table after its first release. ``create_all`` makes missing
# *tables*, but never alters an existing one, so a column added to the model would
# raise "no such column" against a database created by an earlier version. Each
# entry is applied with ``ALTER TABLE ... ADD COLUMN`` only when absent — idempotent
# and safe to run on every boot. SQLite/Postgres both accept this form.
#
# FROZEN — Alembic owns schema changes from now on (see alembic/ and
# :func:`run_migrations`). This list exists only to bootstrap pre-Alembic
# databases: it is consumed exactly once, by the ``0001_baseline`` migration, and
# must NOT be extended for new schema changes. For anything beyond an additive
# column, write a real Alembic revision.
#
# LIMITATION — additive only. This lightweight mechanism handles exactly one kind
# of schema change: adding a new, nullable-or-defaulted column. It deliberately
# does NOT (and cannot safely) handle:
#   * renaming a column        — would silently orphan the old data;
#   * changing a column's type — SQLite can't ALTER a type in place;
#   * dropping a column        — data loss, and SQLite lacks DROP COLUMN pre-3.35;
#   * adding constraints / indexes / non-defaulted NOT NULL columns.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("providers", "drop_opencode_identity_block", "BOOLEAN NOT NULL DEFAULT false"),
    ("providers", "retry_on_zero_token", "BOOLEAN NOT NULL DEFAULT false"),
    ("providers", "proxy_mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),
    ("providers", "proxy_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "key_select_mode", "VARCHAR(32) NOT NULL DEFAULT 'round_robin'"),
    ("providers", "rate_limit_cooldown_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("providers", "model_routes", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "added_by", "INTEGER"),
    ("providers", "added_by_name", "VARCHAR(255)"),
    ("providers", "uuid", "VARCHAR(36)"),
    ("providers", "key_api_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("providers", "key_api_token_hash", "VARCHAR(64)"),
    ("providers", "key_api_token_ciphertext", "TEXT"),
    ("providers", "key_api_token_preview", "VARCHAR(48)"),
    ("api_keys", "pool", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("api_keys", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
    ("api_keys", "rate_limit_until", "TIMESTAMP WITH TIME ZONE"),
    ("api_keys", "added_by", "INTEGER"),
    ("api_keys", "added_by_name", "VARCHAR(255)"),
    ("api_keys", "disabled_since", "TIMESTAMP WITH TIME ZONE"),
    ("audit_logs", "sensitive_ciphertext", "TEXT"),
    ("audit_logs", "scope", "VARCHAR(16) NOT NULL DEFAULT 'admin'"),
    ("audit_logs", "user_agent", "VARCHAR(512)"),
    ("request_logs", "user_agent", "VARCHAR(512)"),
    ("request_logs", "client_type", "VARCHAR(64)"),
    ("request_logs", "is_opencode", "BOOLEAN NOT NULL DEFAULT false"),
    ("request_logs", "debug", "BOOLEAN NOT NULL DEFAULT false"),
    ("request_logs", "upstream_model", "VARCHAR(120)"),
    ("request_logs", "req_method", "VARCHAR(16)"),
    ("request_logs", "debug_attempts", "JSON"),
    ("request_logs", "req_headers", "JSON"),
    ("request_logs", "req_body", "JSON"),
    ("request_logs", "resp_headers", "JSON"),
    ("request_logs", "resp_body", "JSON"),
    ("request_logs", "upstream_url", "VARCHAR(1024)"),
    ("request_logs", "proxy_url", "VARCHAR(512)"),
    ("request_logs", "session_id", "VARCHAR(255)"),
    ("request_logs", "started_at", "TIMESTAMP WITH TIME ZONE"),
    ("request_logs", "finished_at", "TIMESTAMP WITH TIME ZONE"),
    ("request_logs", "first_token_ms", "FLOAT"),
    ("request_logs", "req_status", "VARCHAR(32)"),
    ("request_logs", "client_ip", "VARCHAR(64)"),
    ("request_logs", "attempts_summary", "JSON"),
    ("void_tokens", "debug_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("void_tokens", "auto_disabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("void_tokens", "deleted", "BOOLEAN NOT NULL DEFAULT false"),
    ("void_tokens", "deleted_at", "TIMESTAMP WITH TIME ZONE"),
    ("models", "mapped_id", "VARCHAR(255)"),
    ("models", "display_name", "VARCHAR(255)"),
    ("models", "allowed_role_group_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "login_token_hash", "VARCHAR(64)"),
    ("users", "login_token_prefix", "VARCHAR(32)"),
    ("users", "void_tokens_admin_disabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("users", "team_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("announcements", "target_role_group_ids", "JSON NOT NULL DEFAULT '[]'"),
)


def _add_missing_columns(conn: Any) -> None:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())
    for table, column, ddl in _ADDED_COLUMNS:
        if table not in tables:
            continue  # create_all just made it with the column already present
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# Composite indexes added after a table's first release. ``create_all`` with its
# default ``checkfirst`` skips tables that already exist, so it never adds a new
# index to a pre-existing table — these must be created explicitly. Each entry is
# ``(index_name, table, "col_a, col_b")`` and is issued as ``CREATE INDEX IF NOT
# EXISTS`` (supported by SQLite ≥3.8 and Postgres), making it idempotent and safe
# on every boot.
#
# These indexes are now also declared on the ORM models themselves
# (``RequestLog.__table_args__`` / ``AuditLog.__table_args__``) so Alembic
# autogenerate treats them as part of the schema. This FROZEN list remains only
# to heal pre-Alembic databases (consumed once by ``0001_baseline``); new indexes
# belong in an Alembic revision.
_ADDED_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_request_logs_user_sub_id", "request_logs", "user_sub, id"),
    ("ix_request_logs_model_id", "request_logs", "model, id"),
    ("ix_request_logs_provider_name_id", "request_logs", "provider_name, id"),
    ("ix_request_logs_token_id_id", "request_logs", "token_id, id"),
    ("ix_request_logs_success_id", "request_logs", "success, id"),
    ("ix_audit_logs_scope_id", "audit_logs", "scope, id"),
    ("ix_audit_logs_action_id", "audit_logs", "action, id"),
    ("ix_audit_logs_actor_sub_id", "audit_logs", "actor_sub, id"),
)


def _ensure_indexes(conn: Any) -> None:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())
    for name, table, columns in _ADDED_INDEXES:
        if table not in tables:
            continue  # create_all just made it; its own indexes come with it
        conn.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"
        )


def _backfill_provider_uuids(conn: Any) -> None:
    """Assign a uuid to any provider row missing one.

    ``providers.uuid`` was added after the first release; rows created earlier (or
    via the raw ALTER above) have a NULL/blank value. Generate one per row so the
    column can be relied on as a stable public id. Idempotent.
    """
    import uuid as uuid_lib

    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(conn)
    if "providers" not in set(inspector.get_table_names()):
        return
    rows = conn.execute(
        text("SELECT id FROM providers WHERE uuid IS NULL OR uuid = ''")
    ).fetchall()
    for (pid,) in rows:
        conn.execute(
            text("UPDATE providers SET uuid = :u WHERE id = :i"),
            {"u": str(uuid_lib.uuid4()), "i": pid},
        )


# Process-wide singleton, set during application startup (main.lifespan).
_db: Database | None = None


def init_database(url: str, *, echo: bool = False) -> Database:
    global _db
    _db = Database(url, echo=echo)
    return _db


def get_database() -> Database:
    if _db is None:  # pragma: no cover - misconfiguration guard
        raise RuntimeError("Database not initialised. Call init_database() first.")
    return _db


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding the request-scoped session.

    The session is created lazily and committed by ``RequestSessionMiddleware``
    *before* the response is sent — so a follow-up read in the same client (e.g.
    the dashboard reloading a table after an add) always sees the write. Falls
    back to a standalone transactional session when used outside an HTTP request
    (rare; keeps the dependency usable in isolation).
    """
    existing = _request_session.get()
    if existing is not None:
        yield existing
        return
    async with get_database().session() as session:
        yield session


class RequestSessionMiddleware:
    """ASGI middleware that owns a per-request DB session.

    Commits at ``http.response.start`` (before the body is sent) on success, and
    rolls back on error. This closes the race where the yield-dependency commit
    would otherwise run *after* the response, letting an immediate refetch read
    stale data.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        session = get_database().session_factory()
        token = _request_session.set(session)
        client_token = _request_client.set(_extract_request_client(scope))
        committed = False

        async def send_wrapper(message: _Message) -> None:
            nonlocal committed
            if message.get("type") == "http.response.start" and not committed:
                committed = True
                if session.in_transaction():
                    await session.commit()
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            # Client disconnected mid-request. CancelledError is a BaseException
            # (not Exception), so the except-Exception branch below misses it.
            # Roll back the uncommitted transaction and swallow the cancellation
            # — there is nobody to send an error response to. The finally block
            # returns the connection to the pool so the GC never has to.
            await _safe_rollback(session)
        except Exception:
            await _safe_rollback(session)
            raise
        finally:
            # Shield close() so the connection is always returned to the pool,
            # even if a second cancellation arrives during shutdown.
            await _safe_close(session)
            _request_session.reset(token)
            _request_client.reset(client_token)


def _extract_request_client(scope: _Scope) -> tuple[str | None, str | None]:
    """Pull the client IP and user-agent out of an ASGI scope.

    ``scope["client"]`` is ``(host, port)``; the user-agent lives in the
    header list as raw bytes. Returns ``(None, None)`` for pieces that aren't
    present (e.g. a server without a client address).
    """
    ip: str | None = None
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client and isinstance(client[0], str):
        ip = client[0]
    user_agent: str | None = None
    for name, value in scope.get("headers", []) or []:
        if name.lower() == b"user-agent":
            user_agent = value.decode("latin-1", errors="replace")
            break
    return ip, user_agent


async def _safe_rollback(session: AsyncSession) -> None:
    """Roll back a session, swallowing errors during cancellation/shutdown."""
    if not session.in_transaction():
        return
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.shield(session.rollback())


async def _safe_close(session: AsyncSession) -> None:
    """Close a session so its connection returns to the pool.

    Shielded so that a pending task cancellation does not interrupt the
    close — without this, SQLAlchemy leaks connections that the garbage
    collector later terminates with noisy tracebacks.
    """
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.shield(session.close())
