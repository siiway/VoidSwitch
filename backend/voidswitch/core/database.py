"""Async database engine, session factory, and initialisation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
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

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Transactional scope: commit on success, rollback on error."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
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
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("providers", "drop_opencode_identity_block", "BOOLEAN NOT NULL DEFAULT 0"),
    ("providers", "proxy_mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),
    ("providers", "proxy_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "model_routes", "JSON NOT NULL DEFAULT '[]'"),
    ("providers", "added_by", "INTEGER"),
    ("providers", "added_by_name", "VARCHAR(255)"),
    ("api_keys", "pool", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("api_keys", "added_by", "INTEGER"),
    ("api_keys", "added_by_name", "VARCHAR(255)"),
    ("audit_logs", "sensitive_ciphertext", "TEXT"),
    ("audit_logs", "scope", "VARCHAR(16) NOT NULL DEFAULT 'admin'"),
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
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()
            _request_session.reset(token)
