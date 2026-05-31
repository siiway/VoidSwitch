"""Configuration loading.

Config comes from a YAML file (default ``config.yaml`` next to the project root,
overridable via the ``VOIDSWITCH_CONFIG`` env var) merged with environment
variables prefixed ``VOIDSWITCH_`` (``__`` is the nesting separator).

Per project rules this file carries ONLY server info and Prism OAuth credentials;
all operational thresholds live in the database and are tuned at runtime.
"""

from __future__ import annotations

import contextlib
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _project_root() -> Path:
    # voidswitch/core/config.py -> backend/
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    import os

    env = os.environ.get("VOIDSWITCH_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "config.yaml"


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8080
    base_url: str = "http://localhost:8080"
    # Where to send the browser after a successful OAuth login. Defaults to the
    # first CORS origin when left empty.
    frontend_url: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    secret_key: str = ""
    session_ttl_minutes: int = 720
    log_level: str = "INFO"
    log_console: bool = True
    # Debug mode: forces the log level to DEBUG and turns on verbose request
    # tracing — every inbound gateway request and every outbound upstream request
    # (URL, redacted headers, body) is logged. Noisy; never enable in production.
    # Toggle via VOIDSWITCH_SERVER__DEBUG=true.
    debug: bool = False
    # Dev mode: enables a no-OAuth "Developer sign-in" that mints an owner
    # session without Prism. NEVER enable in production. Toggle via
    # VOIDSWITCH_SERVER__DEV_MODE=true.
    dev_mode: bool = False


class DatabaseSettings(BaseSettings):
    url: str = "sqlite+aiosqlite:///./voidswitch.db"
    echo: bool = False


class PrismSettings(BaseSettings):
    issuer: str = "https://prism.siiway.org"
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])

    @property
    def authorize_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/api/oauth/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/api/oauth/token"

    @property
    def userinfo_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/api/oauth/userinfo"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/jwks.json"


class AdminSettings(BaseSettings):
    owner_subs: list[str] = Field(default_factory=list)
    owner_emails: list[str] = Field(default_factory=list)
    trust_prism_admin: bool = True
    bootstrap_first_user: bool = True


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_prefix="VOIDSWITCH_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    prism: PrismSettings = Field(default_factory=PrismSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: explicit init kwargs > env vars > YAML file > defaults.
        return (init_settings, env_settings, _YamlSource(settings_cls))

    @model_validator(mode="after")
    def _finalise(self) -> Settings:
        if not self.prism.redirect_uri:
            self.prism.redirect_uri = f"{self.server.base_url.rstrip('/')}/api/auth/callback"
        if not self.server.secret_key:
            self.server.secret_key = _load_or_create_secret()
        if not self.server.frontend_url and self.server.cors_origins:
            self.server.frontend_url = self.server.cors_origins[0]
        return self


class _YamlSource(PydanticBaseSettingsSource):
    """Reads the YAML config file as a settings source."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        path = _config_path()
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._data: dict[str, Any] = data if isinstance(data, dict) else {}
        else:
            self._data = {}

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


def _load_or_create_secret() -> str:
    path = _project_root() / ".secret_key"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    # Read-only FS (e.g. container) — fall back to an ephemeral key.
    with contextlib.suppress(OSError):
        path.write_text(value, encoding="utf-8")
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
