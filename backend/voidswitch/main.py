"""FastAPI application factory and lifecycle wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from voidswitch import __version__
from voidswitch.api import (
    announcements as announcements_api,
    auth as auth_api,
    install as install_api,
    me as me_api,
    models as models_api,
    provider_api,
    proxy as proxy_api,
    usage as usage_api,
)
from voidswitch.api.admin import (
    keys as keys_api,
    logs as logs_api,
    providers as providers_api,
    proxies as proxies_api,
    reveal as reveal_api,
    role_groups as role_groups_api,
    settings as settings_api,
    stats as stats_api,
    system as system_api,
    tokens as tokens_api,
    users as users_api,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import RequestSessionMiddleware, init_database
from voidswitch.core.logging import configure_logging, get_logger
from voidswitch.services import role_groups, settings_store
from voidswitch.services.network import get_pool
from voidswitch.tasks.balance_probe import run_balance_probe
from voidswitch.tasks.balance_rescan import run_balance_rescan
from voidswitch.tasks.log_cleanup import run_log_cleanup
from voidswitch.tasks.manager import PeriodicTask, TaskManager
from voidswitch.tasks.proxy_resurrector import run_proxy_resurrector

log = get_logger("main")
error_log = get_logger("error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = init_database(settings.database.url, echo=settings.database.echo)
    await db.create_all()
    async with db.session() as session:
        await settings_store.ensure_defaults(session)
        await settings_store.load_all(session)
        await role_groups.ensure_moderator_group(session)
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
            name="balance_rescan",
            tick=run_balance_rescan,
            interval_key="balance_rescan_interval_seconds",
            enabled_key="balance_rescan_enabled",
            min_interval=60,
        )
    )
    manager.register(
        PeriodicTask(
            name="proxy_resurrector",
            tick=run_proxy_resurrector,
            interval_key="proxy_probe_interval_seconds",
            enabled_key="proxy_health_check_enabled",
            min_interval=15,
        )
    )
    manager.register(
        PeriodicTask(
            name="log_cleanup",
            tick=run_log_cleanup,
            interval_key="log_cleanup_interval_seconds",
            enabled_key="log_cleanup_enabled",
            min_interval=300,
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
        # Swagger UI lives at /swagger (the usage docs are a separate public
        # VitePress site, not served by the backend). ReDoc + the raw schema keep
        # their defaults.
        docs_url="/swagger",
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

    # Catch-all: any exception not already handled by FastAPI's HTTPException /
    # RequestValidationError handlers lands here so it is always logged through
    # structlog (with traceback) before the 500 goes out — no silent server errors.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        error_log.error(
            "unhandled_exception",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

    # Public gateway.
    app.include_router(proxy_api.router)
    # Public one-line OpenCode installer.
    app.include_router(install_api.router)
    # Auth + self-service.
    app.include_router(auth_api.router)
    app.include_router(me_api.router)
    app.include_router(announcements_api.router)
    app.include_router(models_api.router)
    # Admin.
    app.include_router(providers_api.router)
    app.include_router(keys_api.router)
    app.include_router(proxies_api.router)
    app.include_router(tokens_api.router)
    app.include_router(settings_api.router)
    app.include_router(logs_api.router)
    app.include_router(reveal_api.router)
    app.include_router(users_api.router)
    app.include_router(role_groups_api.router)
    app.include_router(stats_api.router)
    app.include_router(usage_api.router)
    app.include_router(system_api.router)

    # Mounted per-provider key-management API (its own Swagger UI + OpenAPI
    # schema at /provider-api/docs). Authenticated by a provider's vsk-… token.
    app.mount("/provider-api", provider_api.subapp)

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
                "openai_responses": "/v1/responses",
                "anthropic": "/v1/messages",
                "models": "/v1/models",
                "swagger": "/swagger",
                "provider_key_api_docs": "/provider-api/docs",
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
