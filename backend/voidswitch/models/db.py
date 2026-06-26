"""SQLAlchemy 2.0 async ORM models."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from voidswitch.constants import KeyStatus, ProxyMode, ProxyStatus, Role


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> str:
    return str(uuid_lib.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    picture: Mapped[str | None] = mapped_column(Text, default=None)
    role: Mapped[str] = mapped_column(String(32), default=Role.MEMBER.value)
    prism_role: Mapped[str | None] = mapped_column(String(32), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    tokens: Mapped[list[VoidToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class VoidToken(Base, TimestampMixin):
    __tablename__ = "void_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Empty list means "all models permitted".
    allowed_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    rpm_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    daily_quota: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited (requests/day)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped[User] = relationship(back_populates="tokens", lazy="selectin")

    @property
    def username(self) -> str | None:
        """Human-friendly owner label for API output."""
        user = self.user
        if user is None:
            return None
        label = user.username or user.name or user.email
        return f"{label}#{user.id}" if label else None


class ModelEntry(Base, TimestampMixin):
    """Catalog metadata for a model id offered across the platform.

    The *available* model ids come from the providers' ``models`` lists (and
    alias routes); this table layers human-facing metadata on top of them: a
    description and a custom OpenCode model config (deep-merged into the model
    block the OpenCode plugin builds). Rows are created on demand — either by an
    admin editing a model, by the "sync from providers" action, or by a user
    refreshing the catalog through the OpenCode ``/models`` command.
    """

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Optional public alias. When set, the model is advertised (and must be
    # called) under this id instead of ``model_id``; the raw ``model_id`` is
    # hidden from /v1/models and rejected at the gateway, so the upstream id
    # never leaks and two providers' colliding ids can be disambiguated.
    mapped_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # Custom OpenCode model config, deep-merged into the plugin's built model.
    opencode_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # When False the model is hidden from the advertised list (/v1/models) and
    # the OpenCode picker, even if a provider still serves it.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Who first registered metadata for this model (id + display-name snapshot).
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable public identifier, independent of the autoincrement primary key.
    # Used by the mounted provider key-management API so external integrations
    # reference a provider by an opaque, non-guessable id.
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # Adapter key, e.g. "openai", "anthropic", "deepseek".
    type: Mapped[str] = mapped_column(String(64), default="openai")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = preferred
    weight: Mapped[int] = mapped_column(Integer, default=1)
    # Supported model names / glob patterns ("*" matches anything).
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Optional remap of inbound model name -> upstream model name.
    model_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Alias routes: each {"alias", "upstream", "pool"} maps an inbound model name
    # to an upstream model served by a specific key pool. Lets e.g.
    # "deepseek-v4-flash-lkd" → "deepseek-v4-flash" on the "leaked" key pool, while
    # "deepseek-v4-flash" → same upstream on the "members" pool. See ApiKey.pool.
    model_routes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    balance_url: Mapped[str | None] = mapped_column(String(512), default=None)
    extra_headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=0)  # 0 = use global
    # claude-code masquerade only: when True, drop the inbound client's entire
    # "You are OpenCode…" system block instead of scrubbing it in place.
    drop_opencode_identity_block: Mapped[bool] = mapped_column(Boolean, default=False)
    # Outbound routing: "all" (any active proxy), "direct" (never proxy), or
    # "selected" (only the proxy IDs in proxy_ids). See constants.ProxyMode.
    proxy_mode: Mapped[str] = mapped_column(String(16), default=ProxyMode.ALL.value)
    # Proxy IDs this provider may use when proxy_mode == "selected".
    proxy_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Who created this provider (id + a display-name snapshot). Lets members
    # manage only the providers they added; null for legacy/seeded rows.
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    # Optional per-provider "key-management API key": a programmatic credential
    # that grants access to manage *this provider's* upstream keys through the
    # mounted key-management sub-app. Disabled by default; only (co-)owners may
    # enable, rotate, or reveal it. ``key_api_token_hash`` is the lookup hash,
    # ``key_api_token_ciphertext`` the at-rest encrypted plaintext (so owners can
    # reveal it later), and ``key_api_token_preview`` a short non-secret label.
    key_api_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    key_api_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    key_api_token_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    key_api_token_preview: Mapped[str | None] = mapped_column(String(48), default=None)

    keys: Mapped[list[ApiKey]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", lazy="selectin"
    )


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("provider_id", "key_hash", name="uq_provider_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    key_ciphertext: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    key_preview: Mapped[str] = mapped_column(String(32), default="")
    # Optional pool tag, e.g. "leaked" / "members". Empty = untagged. A model
    # route with a matching pool restricts dispatch to keys carrying that tag.
    pool: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default=KeyStatus.ACTIVE.value, index=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    balance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    # When the key was first moved out of the active state (insufficient balance,
    # invalid, etc.). Used to age out long-dead keys (e.g. "no balance for N days")
    # and cleared whenever the key is re-enabled. Null while active.
    disabled_since: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Who added this key (id + a display-name snapshot). Lets members manage
    # only the keys they added; null for legacy/seeded rows.
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    # When enabled, all requests routed through this key record full
    # request/response detail (headers, body) for debugging.
    debug_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    provider: Mapped[Provider] = relationship(back_populates="keys", lazy="selectin")


class Proxy(Base, TimestampMixin):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # e.g. http://user:pass@host:port, socks5://host:port. Empty = direct.
    url: Mapped[str] = mapped_column(String(512), default="", unique=True)
    # Bind outbound sockets to this local source IP (httpx local_address).
    local_address: Mapped[str | None] = mapped_column(String(64), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default=ProxyStatus.ACTIVE.value, index=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    actor_sub: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), default=None)
    action: Mapped[str] = mapped_column(String(120), default="")
    # "admin" for management-surface actions, "self" for self-service ones
    # (sign-in/out, a user's own Void-Tokens). Lets the dashboard filter the
    # trail down to administrative actions only.
    scope: Mapped[str] = mapped_column(String(16), default="admin", index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), default=None)
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    # Encrypted (Fernet) JSON blob with owner-only sensitive context, e.g. the
    # plaintext of keys added or the full details of a deleted key. Never exposed
    # to admins or members; revealed to owners on explicit, confirmed request.
    sensitive_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    token_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    user_sub: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    provider_id: Mapped[int | None] = mapped_column(Integer, default=None)
    provider_name: Mapped[str | None] = mapped_column(String(120), default=None)
    key_id: Mapped[int | None] = mapped_column(Integer, default=None)
    proxy_id: Mapped[int | None] = mapped_column(Integer, default=None)
    model: Mapped[str | None] = mapped_column(String(120), default=None, index=True)
    inbound_style: Mapped[str | None] = mapped_column(String(32), default=None)
    upstream_style: Mapped[str | None] = mapped_column(String(32), default=None)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # Client metadata
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    client_type: Mapped[str | None] = mapped_column(String(64), default=None)
    is_opencode: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether this row was recorded with debug-level detail (full req/resp).
    debug: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Debug-only fields — populated only when the key has debug_enabled=True.
    req_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    req_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    resp_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    resp_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    upstream_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    proxy_url: Mapped[str | None] = mapped_column(String(512), default=None)
