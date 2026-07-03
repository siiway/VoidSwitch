"""Async database engine, session factory, and initialisation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
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


# Columns added to a table after its first release. ``create_all`` makes missing
# *tables*, but never alters an existing one, so a column added to the model would
# raise "no such column" against a database created by an earlier version. Each
# entry is applied with ``ALTER TABLE ... ADD COLUMN`` only when absent — idempotent
# and safe to run on every boot. SQLite/Postgres both accept this form.
#
# LIMITATION: This mechanism supports additive changes only (new columns).
# Column renames, type changes, or deletions require a separate migration
# strategy (e.g. Alembic) and are not handled here. Attempting such changes
# without a proper migration will break the database.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("providers", "drop_opencode_identity_block", "BOOLEAN NOT NULL DEFAULT 0"),
    ("providers", "proxy_mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),
    ("providers", "proxy_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "key_select_mode", "VARCHAR(32) NOT NULL DEFAULT 'round_robin'"),
    ("providers", "rate_limit_cooldown_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("providers", "model_routes", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "added_by", "INTEGER"),
    ("providers", "added_by_name", "VARCHAR(255)"),
    ("providers", "uuid", "VARCHAR(36)"),
    ("providers", "key_api_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("providers", "key_api_token_hash", "VARCHAR(64)"),
    ("providers", "key_api_token_ciphertext", "TEXT"),
    ("providers", "key_api_token_preview", "VARCHAR(48)"),
    ("api_keys", "pool", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("api_keys", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
    ("api_keys", "rate_limit_until", "DATETIME"),
    ("api_keys", "added_by", "INTEGER"),
    ("api_keys", "added_by_name", "VARCHAR(255)"),
    ("api_keys", "disabled_since", "DATETIME"),
    ("audit_logs", "sensitive_ciphertext", "TEXT"),
    ("audit_logs", "scope", "VARCHAR(16) NOT NULL DEFAULT 'admin'"),
    ("audit_logs", "user_agent", "VARCHAR(512)"),
    ("request_logs", "user_agent", "VARCHAR(512)"),
    ("request_logs", "client_type", "VARCHAR(64)"),
    ("request_logs", "is_opencode", "BOOLEAN NOT NULL DEFAULT 0"),
    ("request_logs", "debug", "BOOLEAN NOT NULL DEFAULT 0"),
    ("request_logs", "upstream_model", "VARCHAR(120)"),
    ("request_logs", "req_method", "VARCHAR(16)"),
    ("request_logs", "debug_attempts", "JSON"),
    ("request_logs", "req_headers", "JSON"),
    ("request_logs", "req_body", "JSON"),
    ("request_logs", "resp_headers", "JSON"),
    ("request_logs", "resp_body", "JSON"),
    ("request_logs", "upstream_url", "VARCHAR(1024)"),
    ("request_logs", "proxy_url", "VARCHAR(512)"),
    ("void_tokens", "debug_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("models", "mapped_id", "VARCHAR(255)"),
    ("models", "display_name", "VARCHAR(255)"),
    ("models", "allowed_role_group_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "void_tokens_admin_disabled", "BOOLEAN NOT NULL DEFAULT 0"),
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


def _backfill_provider_uuids(conn: Any) -> None:
    """Assign a uuid to any provider row missing one.

    ``providers.uuid`` was added after the first release; rows created earlier (or
    via the raw ALTER above) have a NULL/blank value. Generate one per row so the
    column can be relied on as a stable public id. Idempotent.
    """
    import uuid as uuid_lib

    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

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
