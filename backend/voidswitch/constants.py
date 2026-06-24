"""Shared enums and status constants (stored as plain strings in the DB)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    CO_OWNER = "co-owner"
    ADMIN = "admin"
    MEMBER = "member"


class KeyStatus(StrEnum):
    ACTIVE = "active"
    INVALID = "invalid"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class ProxyStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ApiStyle(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# Inbound header an in-the-know client (the OpenCode plugin) sets so the gateway
# can tailor its error signalling. Plain clients never send it and are unaffected.
CLIENT_HINT_HEADER = "x-voidswitch-client"
OPENCODE_CLIENT_HINT = "opencode-plugin"

# Non-standard status code returned *only* to the OpenCode plugin when no upstream
# is available (no usable key / route / all keys exhausted). A bare 502 carries the
# "Bad Gateway" reason phrase, which reads like the relay itself broke; this code is
# in uvicorn's 100-599 range so it ships with an empty reason phrase, and the plugin
# maps it to a clear "Upstream Failed" status. Other clients still receive 502.
UPSTREAM_UNAVAILABLE_STATUS = 543


class ProxyMode(StrEnum):
    """How a provider chooses its outbound route."""

    ALL = "all"  # use any active proxy (global pool), direct only if none exist
    DIRECT = "direct"  # never use a proxy — always connect directly
    SELECTED = "selected"  # only the proxies assigned in Provider.proxy_ids


# Default operational thresholds; seeded into the settings table on first boot
# and editable at runtime from the dashboard.
DEFAULT_SETTINGS: dict[str, object] = {
    "max_proxy_failures": 3,
    "max_key_failures": 3,
    "proxy_probe_interval_seconds": 120,
    "balance_probe_interval_seconds": 1800,
    # Slow background rescan that re-checks keys disabled for insufficient balance
    # and re-enables any that have been topped up. Defaults to once per day.
    "balance_rescan_interval_seconds": 86400,
    # How long (seconds) a rate-limited key stays parked before it can be retried.
    # After this interval elapses, the key is re-attempted on the next dispatch.
    "rate_limit_recovery_seconds": 180,
    # Throttle for on-demand "rescan all balances": at most this many balance
    # requests per second. 0 = unthrottled (fire as fast as possible).
    "balance_scan_rate_per_second": 5,
    "request_timeout_seconds": 300,
    "connect_timeout_seconds": 15,
    "max_retries": 6,
    "stream_idle_timeout_seconds": 120,
    "auto_disable_zero_balance": True,
    "balance_probe_enabled": True,
    "balance_rescan_enabled": True,
    "proxy_resurrector_enabled": True,
    "proxy_probe_url": "https://api.openai.com/v1/models",
    # Log retention. A background task deletes audit/request log rows older than
    # the configured number of days, to keep the database from growing without
    # bound. 0 = keep forever (no automatic deletion). The cleanup task itself
    # runs on the interval below and can be disabled outright.
    "audit_log_retention_days": 0,
    "request_log_retention_days": 0,
    "log_cleanup_enabled": True,
    "log_cleanup_interval_seconds": 86400,
    "opencode_default_model": "claude-opus-4-8",
    "opencode_small_model": "claude-haiku-4-5-20251001",
}
