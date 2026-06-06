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
}
