"""FastAPI application factory and lifecycle wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from voidswitch import __version__
from voidswitch.api import auth as auth_api
from voidswitch.api import install as install_api
from voidswitch.api import me as me_api
from voidswitch.api import proxy as proxy_api
from voidswitch.api.admin import (
    keys as keys_api,
)
from voidswitch.api.admin import (
    logs as logs_api,
)
from voidswitch.api.admin import (
    providers as providers_api,
)
from voidswitch.api.admin import (
    proxies as proxies_api,
)
from voidswitch.api.admin import (
    settings as settings_api,
)
from voidswitch.api.admin import (
    stats as stats_api,
)
from voidswitch.api.admin import (
    system as system_api,
)
from voidswitch.api.admin import (
    tokens as tokens_api,
)
from voidswitch.api.admin import (
    users as users_api,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import RequestSessionMiddleware, init_database
from voidswitch.core.logging import configure_logging, get_logger
from voidswitch.services import settings_store
from voidswitch.services.network import get_pool
from voidswitch.tasks.balance_probe import run_balance_probe
from voidswitch.tasks.manager import PeriodicTask, TaskManager
from voidswitch.tasks.proxy_resurrector import run_proxy_resurrector

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = init_database(settings.database.url, echo=settings.database.echo)
    await db.create_all()
    async with db.session() as session:
        await settings_store.ensure_defaults(session)
        await settings_store.load_all(session)
    log.info("database_ready", url=_redact(settings.database.url))

    manager = TaskManager()
    manager.register(
        PeriodicTask(
            name="balance_probe",
            tick=run_balance_probe,
            interval_key="balance_probe_interval_seconds",
            enabled_key="balance_probe_enabled",
            min_interval=30,
        )
    )
    manager.register(
        PeriodicTask(
            name="proxy_resurrector",
            tick=run_proxy_resurrector,
            interval_key="proxy_probe_interval_seconds",
            enabled_key="proxy_resurrector_enabled",
            min_interval=15,
        )
    )
    manager.start()
    app.state.task_manager = manager
    log.info("voidswitch_started", version=__version__)
    if settings.server.dev_mode:
        log.warning(
            "DEV_MODE_ENABLED",
            detail="OAuth bypass active — /api/auth/dev-login mints owner sessions. "
            "Do NOT use in production.",
        )

    try:
        yield
    finally:
        await manager.stop()
        await get_pool().aclose()
        await db.dispose()
        log.info("voidswitch_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Debug mode forces verbose tracing regardless of the configured log level.
    log_level = "DEBUG" if settings.server.debug else settings.server.log_level
    configure_logging(log_level, console=settings.server.log_console)

    app = FastAPI(
        title="VoidSwitch",
        version=__version__,
        description="Multi-provider LLM API reverse proxy with proxy/key failover.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Inner: owns the per-request DB session and commits before the response.
    app.add_middleware(RequestSessionMiddleware)
    # Outer: CORS wraps everything (added last == outermost).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Public gateway.
    app.include_router(proxy_api.router)
    # Public one-line OpenCode installer.
    app.include_router(install_api.router)
    # Auth + self-service.
    app.include_router(auth_api.router)
    app.include_router(me_api.router)
    # Admin.
    app.include_router(providers_api.router)
    app.include_router(keys_api.router)
    app.include_router(proxies_api.router)
    app.include_router(tokens_api.router)
    app.include_router(settings_api.router)
    app.include_router(logs_api.router)
    app.include_router(users_api.router)
    app.include_router(stats_api.router)
    app.include_router(system_api.router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/", tags=["system"])
    async def root() -> dict[str, object]:
        return {
            "name": "VoidSwitch",
            "version": __version__,
            "endpoints": {
                "openai": "/v1/chat/completions",
                "anthropic": "/v1/messages",
                "models": "/v1/models",
                "docs": "/docs",
            },
        }

    return app


def _redact(url: str) -> str:
    if "@" in url:
        scheme, _, rest = url.partition("://")
        _, _, host = rest.partition("@")
        return f"{scheme}://***@{host}"
    return url


app = create_app()
