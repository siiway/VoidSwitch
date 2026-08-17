"""Shared enums and status constants (stored as plain strings in the DB)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    CO_OWNER = "co-owner"
    ADMIN = "admin"
    MEMBER = "member"


# Stable slug of the built-in "moderator" role group. Owner / co-owner / admin
# are implicitly members of it and may always call every model; it is seeded on
# first boot and can never be deleted or have its model access narrowed.
MODERATOR_GROUP_SLUG = "moderator"

# Ranking of a Prism *team* role, used when evaluating team→role-group mappings
# ("assign when the member's effective role is >= the mapping's role") and the
# main_team_id moderator mapping. Higher = more privileged. There is exactly one
# owner per team; co-owner sits just below it.
TEAM_ROLE_RANK: dict[str, int] = {
    "owner": 4,
    "co-owner": 3,
    "co_owner": 3,
    "coowner": 3,
    "admin": 2,
    "member": 1,
}


class KeyStatus(StrEnum):
    ACTIVE = "active"
    INVALID = "invalid"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class NodeStatus(StrEnum):
    """Status of an outbound node (replaces the old ``ProxyStatus``)."""

    ACTIVE = "active"
    DISABLED = "disabled"


# Kept as an alias so old references / stored values keep working.
ProxyStatus = NodeStatus


class ApiStyle(StrEnum):
    OPENAI = "openai"  # OpenAI Chat Completions (/v1/chat/completions)
    ANTHROPIC = "anthropic"  # Anthropic Messages (/v1/messages)
    OPENAI_RESPONSES = "openai-responses"  # OpenAI Responses API (/v1/responses)


# Inbound header an in-the-know client (the OpenCode plugin) sets so the gateway
# can tailor its error signalling. Plain clients never send it and are unaffected.
CLIENT_HINT_HEADER = "x-voidswitch-client"
OPENCODE_CLIENT_HINT = "opencode-plugin"

# Inbound header carrying a stable, client-supplied session id (the OpenCode
# plugin forwards its native ``sessionID``). When present it is the authoritative
# session identity for the per-session pinned key-select modes, so the gateway
# does not have to infer one from the request body. Consumed at the gateway and
# never forwarded to the upstream provider.
SESSION_HEADER = "x-voidswitch-session"

# Non-standard status code returned *only* to the OpenCode plugin when no upstream
# is available (no usable key / route / all keys exhausted). A bare 502 carries the
# "Bad Gateway" reason phrase, which reads like the relay itself broke; this code is
# in uvicorn's 100-599 range so it ships with an empty reason phrase, and the plugin
# maps it to a clear "Upstream Failed" status. Other clients still receive 502.
UPSTREAM_UNAVAILABLE_STATUS = 543


class NodeType(StrEnum):
    """How a node reaches the internet."""

    DIRECT = "direct"  # 直连 — no proxy, no URL
    HTTP = "http"  # HTTP/HTTPS forward proxy
    SOCKS5 = "socks5"  # SOCKS5 forward proxy
    AGENT = "agent"  # a voidswitch-agent relay (custom protocol)


class KeySelectMode(StrEnum):
    """How a provider picks which upstream key to try first for a request.

    In every mode the dispatcher still falls back through the remaining keys when
    the chosen one is unavailable (rate-limited, disabled, network error, …); the
    mode only governs *which key leads* the per-request candidate ordering.

    * ``round_robin``        — advance to the next key (in manual order) each request.
    * ``random``             — pick a random key each request.
    * ``fallback``           — always lead with the first key in manual order,
                               only moving on when it is unavailable.
    * ``pinned_round_robin`` — pin one key per session (assigned round-robin),
                               reused for that session unless it becomes unavailable.
    * ``pinned_random``      — pin one key per session (assigned at random), same
                               stickiness as ``pinned_round_robin``.
    """

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    FALLBACK = "fallback"
    PINNED_ROUND_ROBIN = "pinned_round_robin"
    PINNED_RANDOM = "pinned_random"


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
    # How long (seconds) a rate-limited key stays parked before it can be retried,
    # used as the fallback when the upstream's 429 carries no ``Retry-After`` header
    # and the provider defines no per-provider cooldown.
    "rate_limit_recovery_seconds": 180,
    # Safety cap (seconds) on any single rate-limit cooldown — even a large
    # ``Retry-After`` or per-provider cooldown is clamped to this so a key can
    # never be parked indefinitely. 0 = no cap.
    "rate_limit_max_cooldown_seconds": 3600,
    # Throttle for on-demand "rescan all balances": at most this many balance
    # requests per second. 0 = unthrottled (fire as fast as possible).
    "balance_scan_rate_per_second": 5,
    "request_timeout_seconds": 300,
    "connect_timeout_seconds": 15,
    "max_retries": 6,
    "stream_idle_timeout_seconds": 120,
    # Hard wall-clock cap on a single request (streaming included): when a
    # request runs past this, the connection is force-cut and the log row marked
    # ``terminated`` (已切断). Streaming has no other total-duration bound — only
    # the idle timeout — so a slow-trickling or leaked upstream connection could
    # otherwise stay "pending" forever. 0 = disabled (no total cap).
    "response_timeout_seconds": 3600,
    # Dashboard session (login-state) duration in minutes, min 60. 0 / empty →
    # follow the `expires_in` returned by Prism at login; if Prism sends none,
    # fall back to the server config's session_ttl_minutes.
    "session_ttl_minutes": 0,
    "auto_disable_zero_balance": True,
    "balance_probe_enabled": True,
    "balance_rescan_enabled": True,
    # Master switch for automatic proxy health management. When on, the gateway
    # probes disabled proxies to re-enable recovered ones (the resurrector task)
    # AND auto-disables a proxy that fails past ``max_proxy_failures``. Turn it
    # off to leave proxy connectivity entirely to an external manager (e.g. a
    # mihomo instance): no health-check probing, no auto-disable, no auto-enable.
    "proxy_health_check_enabled": True,
    "proxy_probe_url": "https://api.openai.com/v1/models",
    # Log retention. A background task deletes audit/request log rows older than
    # the configured number of days, to keep the database from growing without
    # bound. 0 = keep forever (no automatic deletion). The cleanup task itself
    # runs on the interval below and can be disabled outright.
    "audit_log_retention_days": 0,
    "request_log_retention_days": 0,
    "debug_log_retention_days": 0,
    # How long to keep the daily usage rollups and session spans that back the
    # activity heatmap and its statistics. Independent of request-log retention so
    # the heatmap survives request-log pruning. 0 = keep forever; any positive
    # value must be at least one year (365 days) — enforced on save.
    "heatmap_retention_days": 365,
    "log_cleanup_enabled": True,
    "log_cleanup_interval_seconds": 86400,
    "opencode_default_model": "claude-opus-4-8",
    "opencode_small_model": "claude-haiku-4-5-20251001",
    # Rows per page in the dashboard's Logs tables (audit + request logs).
    "logs_page_size": 50,
    # Max simultaneous live-log-stream (SSE) connections a single user may hold
    # open at once. Extra connections beyond this are rejected with 429.
    "log_stream_max_connections": 2,
    # Proxy switching. When False the gateway stops rotating/failover over the
    # node pool: every upstream request goes through ``static_proxy_url`` (or, if
    # that is empty, directly / via the process HTTP(S)_PROXY env vars), and a
    # node is never auto-disabled on failure. Use this when an external proxy
    # (e.g. mihomo) already handles egress routing.
    "proxy_switching_enabled": True,
    # The single proxy URL used for every request when proxy switching is off.
    # Empty → connect directly, falling back to the HTTP_PROXY/HTTPS_PROXY/
    # ALL_PROXY environment variables when present.
    "static_proxy_url": "",
    # Node groups.
    # URL probed by idle node-health checks when a group doesn't override it.
    "node_default_probe_url": "https://api.openai.com/v1/models",
    # Idle probe interval (seconds) when a group doesn't override it.
    "node_probe_interval_seconds": 120,
    # Node dynamic-ranking weights: score = alpha·ewma_latency_ms +
    # beta·failed_count + gamma·threshold-proximity penalty. Nodes are tried in
    # ascending score order; ``weight`` only spreads picks when scores tie.
    "node_rank_alpha": 1.0,
    "node_rank_beta": 100.0,
    "node_rank_gamma": 1000.0,
    # How long (seconds) a node's EWMA latency halves when idling without
    # measurements — keeps a formerly-slow node able to recover.
    "node_rank_ewma_half_life_seconds": 300,
    # models.dev catalog sync. The registry is pulled from
    # https://models.dev/api.json and used as *placeholder* metadata for exposed
    # models that were matched to a models.dev model id (never overwriting
    # explicitly filled fields). 0 = disabled.
    "models_dev_sync_interval_minutes": 1440,
    # How many announcements to show inline on the dashboard's home panel before
    # the "view all" action is needed to open the rest. 0 = show none inline
    # (only the full-list dialog). The login popup always shows recent ones.
    "announcements_home_count": 3,
    # Per-user abuse rate limits (sliding window, in-process, single-node).
    # Enforced for EVERYONE — including owners — with each user counted
    # independently. 0 max = disabled.
    #
    # "operation" covers mutating dashboard/management actions (POST/PUT/PATCH/
    # DELETE on the /api surface). Setting it too low is refused on save so an
    # owner can never lock themselves (and everyone) out of the dashboard.
    "operation_rate_limit_window_seconds": 10,
    "operation_rate_limit_max_requests": 0,
    # "call" covers the OpenAI/Anthropic gateway endpoints (/v1/chat/completions,
    # /v1/messages).
    "call_rate_limit_window_seconds": 60,
    "call_rate_limit_max_requests": 0,
    # Outbound connection pool sizing. Tune these up for high-concurrency streaming
    # workloads to avoid PoolTimeout; tune them down if memory/port pressure is a
    # concern. Effective only after a restart (new clients are created with the
    # current value at that point, and existing clients are not retroactively
    # resized).
    "max_connections": 400,
    "max_keepalive_connections": 150,
}
