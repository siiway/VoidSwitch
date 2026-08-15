"""Alembic environment for VoidSwitch (async SQLAlchemy, SQLite + PostgreSQL).

The migration URL is resolved from the application's own settings
(``voidswitch.core.config.Settings``) so the same tree serves every deployment
(SQLite for dev/tests, PostgreSQL in production) without secrets in this file.

Two invocation modes are supported:

* **CLI** (``alembic upgrade head``, ``alembic check``, ``alembic revision
  --autogenerate``) — an async engine is built from the resolved URL and the
  migrations run via ``asyncio.run``.
* **Embedded** (the app runs ``upgrade head`` at startup) — the caller passes an
  already-open connection through ``config.attributes["connection"]`` (wrapped by
  SQLAlchemy's ``Connection.run_sync``), so migrations run inside the app's own
  event loop instead of spawning a fresh one.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the backend package importable regardless of the invocation directory.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from voidswitch.models.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """The app-configured database URL (VOIDSWITCH_DATABASE__URL / config.yaml)."""
    # Allow an explicit override for tooling; otherwise follow the app settings.
    url = config.get_main_option("sqlalchemy.url")
    if url and url != "driver://user:pass@localhost/dbname":
        return url
    from voidswitch.core.config import get_settings

    return get_settings().database.url


def _configure(
    *,
    connection: Connection | None = None,
    url: str | None = None,
    literal_binds: bool = False,
) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place; batch mode recreates the table
        # there while PostgreSQL keeps plain ALTERs (no-op for engines that don't
        # need it). Also keeps autogenerate output portable across both.
        render_as_batch=True,
        compare_type=True,
        literal_binds=literal_binds,
        dialect_opts={"paramstyle": "named"},
    )


def run_migrations_offline() -> None:
    _configure(url=_resolve_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(sync_connection: Connection) -> None:
    _configure(connection=sync_connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """CLI mode: build an async engine from the resolved URL and run inside a
    fresh event loop (safe because the CLI has no running loop)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        url=_resolve_url(),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Embedded mode: the application supplies an open (already-sync-wrapped)
    # connection via config.attributes so migrations run on the app's own loop.
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
