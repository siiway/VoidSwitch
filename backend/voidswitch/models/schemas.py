"""Pydantic v2 request/response schemas for the admin & auth API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class LoginStart(BaseModel):
    authorize_url: str
    state: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sub: str
    username: str | None = None
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    role: str
    # The role Prism reported at last login. Surfaced so the dashboard can flag
    # a "local admin override" (VS role=admin while Prism still says member).
    prism_role: str | None = None
    enabled: bool
    last_login_at: dt.datetime | None = None
    created_at: dt.datetime


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


class ModelRoute(BaseModel):
    """Maps an inbound model alias to an upstream model + key pool."""

    alias: str
    upstream: str = ""  # "" → send the alias name unchanged
    pool: str = ""  # "" → use any key; else only keys tagged with this pool


class ProviderBase(BaseModel):
    name: str
    type: str = "openai"
    base_url: str = ""
    enabled: bool = True
    priority: int = 100
    weight: int = 1
    models: list[str] = Field(default_factory=list)
    model_map: dict[str, str] = Field(default_factory=dict)
    balance_url: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 0
    # claude-code only: drop the whole "You are OpenCode…" system block.
    drop_opencode_identity_block: bool = False
    # Outbound routing: "all" | "direct" | "selected" (see constants.ProxyMode).
    proxy_mode: str = "all"
    # Proxy IDs used when proxy_mode == "selected".
    proxy_ids: list[int] = Field(default_factory=list)
    # Alias → upstream model + key-pool routes.
    model_routes: list[ModelRoute] = Field(default_factory=list)


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    weight: int | None = None
    models: list[str] | None = None
    model_map: dict[str, str] | None = None
    balance_url: str | None = None
    extra_headers: dict[str, str] | None = None
    timeout_seconds: int | None = None
    drop_opencode_identity_block: bool | None = None
    proxy_mode: str | None = None
    proxy_ids: list[int] | None = None
    model_routes: list[ModelRoute] | None = None


class ProviderOut(ProviderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    updated_at: dt.datetime
    key_count: int = 0
    active_key_count: int = 0
    # True when this provider's adapter can query a balance endpoint, so the
    # dashboard can surface a balance column and a "refresh balances" action.
    supports_balance: bool = False
    added_by: int | None = None
    added_by_name: str | None = None


# --------------------------------------------------------------------------- #
# Models (platform-wide model catalog + per-model metadata)
# --------------------------------------------------------------------------- #


class ModelOut(BaseModel):
    """A single model id in the catalog, merged with any stored metadata."""

    model_config = ConfigDict(from_attributes=True)

    # Numeric id of the backing metadata row, or null when the model is only
    # served by a provider and has no metadata row yet.
    id: int | None = None
    model_id: str
    # Public alias; when set, this is the only id clients see / may call.
    mapped_id: str | None = None
    # The id clients actually see (``mapped_id`` if set, else ``model_id``).
    public_id: str
    description: str | None = None
    opencode_config: dict = Field(default_factory=dict)
    enabled: bool = True
    # Names of enabled providers that currently serve this model.
    providers: list[str] = Field(default_factory=list)
    # True when at least one enabled provider serves it right now.
    served: bool = False
    # True when a metadata row exists for it.
    registered: bool = False
    added_by_name: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class ModelUpsert(BaseModel):
    """Create or update the metadata for one model id."""

    model_id: str
    # Send "" to clear an existing mapping; omit (null) to leave it unchanged.
    mapped_id: str | None = None
    description: str | None = None
    opencode_config: dict | None = None
    enabled: bool | None = None


class ModelBatchUpdate(BaseModel):
    """Apply the same metadata to many model ids at once."""

    model_ids: list[str]
    description: str | None = None
    opencode_config: dict | None = None
    enabled: bool | None = None


class ModelBatchResult(BaseModel):
    updated: int


class ModelSyncResult(BaseModel):
    added: int
    total: int


# --------------------------------------------------------------------------- #
# API keys (upstream provider credentials)
# --------------------------------------------------------------------------- #


class ApiKeyCreate(BaseModel):
    # Accept many keys at once: newline-separated input from the UI. Each line
    # may carry an inline description after a ``#`` (e.g. ``sk-abc # alice``),
    # which becomes that key's note and overrides the batch-level ``note``.
    keys: list[str]
    weight: int = 1
    note: str | None = None
    pool: str = ""  # optional tag applied to every key in this batch


class ApiKeyUpdate(BaseModel):
    key: str | None = None  # replace the stored secret (re-encrypted on save)
    status: str | None = None
    weight: int | None = None
    note: str | None = None
    pool: str | None = None
    enabled: bool | None = None  # convenience: maps to active/disabled


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    key_preview: str
    pool: str = ""
    status: str
    failed_count: int
    weight: int
    note: str | None = None
    balance: dict = Field(default_factory=dict)
    disabled_reason: str | None = None
    total_requests: int
    last_used_at: dt.datetime | None = None
    last_checked_at: dt.datetime | None = None
    created_at: dt.datetime
    disabled_since: dt.datetime | None = None
    added_by: int | None = None
    added_by_name: str | None = None


class ApiKeyCleanup(BaseModel):
    """Bulk-delete keys in a given disabled state for one provider."""

    # "invalid" → keys whose secret was rejected; "insufficient_balance" → keys
    # that ran out of balance. Only these two targets are accepted.
    target: str
    # For "insufficient_balance": only delete keys that have been disabled for at
    # least this many days (based on ``disabled_since``). 0 = no age requirement.
    min_days: int = 0


class ApiKeyCleanupResult(BaseModel):
    deleted: int


# --------------------------------------------------------------------------- #
# Claude Code subscription OAuth (claude-code provider keys)
# --------------------------------------------------------------------------- #


class ClaudeOAuthStart(BaseModel):
    """Where to send the user to authorize, plus the anti-CSRF state to echo back."""

    authorize_url: str
    state: str


class ClaudeOAuthComplete(BaseModel):
    # ``code`` accepts what Claude's manual page shows (``code#state``), a full
    # callback URL, or the bare code. ``state`` is the value from ``/oauth/start``.
    code: str
    state: str
    note: str | None = None


# --------------------------------------------------------------------------- #
# Proxies
# --------------------------------------------------------------------------- #


class ProxyCreate(BaseModel):
    # Accept newline-separated proxy URLs for batch input.
    urls: list[str]
    local_address: str | None = None
    weight: int = 1
    note: str | None = None


class ProxyUpdate(BaseModel):
    url: str | None = None
    local_address: str | None = None
    enabled: bool | None = None
    status: str | None = None
    weight: int | None = None
    note: str | None = None


class ProxyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    local_address: str | None = None
    enabled: bool
    status: str
    failed_count: int
    weight: int
    latency_ms: float | None = None
    note: str | None = None
    disabled_reason: str | None = None
    last_used_at: dt.datetime | None = None
    last_checked_at: dt.datetime | None = None
    created_at: dt.datetime


# --------------------------------------------------------------------------- #
# Void tokens (client-facing)
# --------------------------------------------------------------------------- #


class VoidTokenCreate(BaseModel):
    name: str = "default"
    allowed_models: list[str] = Field(default_factory=list)
    rpm_limit: int = 0
    daily_quota: int = 0
    expires_at: dt.datetime | None = None
    user_id: int | None = None  # admins may mint tokens for other users


class VoidTokenUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    allowed_models: list[str] | None = None
    rpm_limit: int | None = None
    daily_quota: int | None = None
    expires_at: dt.datetime | None = None


class VoidTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str | None = None
    name: str
    token_prefix: str
    enabled: bool
    allowed_models: list[str] = Field(default_factory=list)
    rpm_limit: int
    daily_quota: int
    total_requests: int
    total_tokens: int
    last_used_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    created_at: dt.datetime


class VoidTokenWithSecret(VoidTokenOut):
    # The plaintext token, returned exactly once on creation/rotation.
    token: str


# --------------------------------------------------------------------------- #
# Settings & logs
# --------------------------------------------------------------------------- #


class SettingsOut(BaseModel):
    values: dict[str, object]


class SettingsUpdate(BaseModel):
    values: dict[str, object]


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: dt.datetime
    actor_sub: str | None = None
    actor_name: str | None = None
    action: str
    # "admin" (management surface) or "self" (a user's own account/tokens).
    scope: str = "admin"
    target_type: str | None = None
    target_id: str | None = None
    detail: dict = Field(default_factory=dict)
    ip: str | None = None
    # True when this entry carries an owner-only sensitive payload that can be
    # revealed via the dedicated endpoint. The payload itself is never inlined.
    has_sensitive: bool = False


class RequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: dt.datetime
    user_sub: str | None = None
    # Resolved, human-friendly caller identity + the Void-Token used.
    user_name: str | None = None
    token_id: int | None = None
    token_name: str | None = None
    provider_name: str | None = None
    model: str | None = None
    inbound_style: str | None = None
    upstream_style: str | None = None
    status_code: int | None = None
    success: bool
    latency_ms: float | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    stream: bool
    attempts: int
    error: str | None = None


class StatsOut(BaseModel):
    providers: int
    active_keys: int
    total_keys: int
    active_proxies: int
    total_proxies: int
    tokens: int
    requests_24h: int
    success_24h: int
    failures_24h: int
    tokens_24h: int


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Usage analytics
# --------------------------------------------------------------------------- #


class UsageTotals(BaseModel):
    """Aggregate call counters for one slice (a period, a user, a token, …)."""

    requests: int = 0
    success: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UsageBucket(UsageTotals):
    """One point on a time series, labelled by its calendar period."""

    period: str


class UsageGroupRow(UsageTotals):
    """Per-entity breakdown row (a user, a token, or a model)."""

    key: str
    label: str
    sublabel: str | None = None


class UsageAnalyticsOut(BaseModel):
    # "all" for staff (platform-wide) or "self" for a member (own traffic only).
    scope: str
    totals: UsageTotals
    daily: list[UsageBucket]
    weekly: list[UsageBucket]
    monthly: list[UsageBucket]
    yearly: list[UsageBucket]
    by_user: list[UsageGroupRow]
    by_token: list[UsageGroupRow]
    by_model: list[UsageGroupRow]
