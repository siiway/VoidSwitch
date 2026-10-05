"""Key selection and fixed outbound routes.

Key selection is unchanged from the flat-pool era. The old *provider→model* and
*provider→route* selection is gone: exposed models resolve through explicit
route flowcharts (``services.model_routing``) and outbound hops come from node
groups (``services.routing``). What remains here is per-provider key ordering
plus the single static route used when routing is switched off.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from voidswitch.constants import KeySelectMode, KeyStatus
from voidswitch.core.redis import get_redis
from voidswitch.models.db import ApiKey, Provider
from voidswitch.services.network import Route

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


_PIN_TTL_SECONDS = 3600
_CURSOR_TTL_SECONDS = 86400
_CURSOR_SCRIPT = """
local value = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return value
"""


def _state_key(kind: str, provider_id: int, pool: str, session_key: str = "") -> str:
    service = get_redis()
    pool_id = hashlib.sha256(pool.encode()).hexdigest()[:24]
    parts: list[object] = ["selector", kind, provider_id, pool_id]
    if session_key:
        parts.append(hashlib.sha256(session_key.encode()).hexdigest())
    return service.key(*parts)


async def _next_cursor(provider_id: int, pool: str) -> int | None:
    try:
        service = get_redis()
        key = _state_key("cursor", provider_id, pool)
        value = await service.client.eval(_CURSOR_SCRIPT, 1, key, _CURSOR_TTL_SECONDS)
        return int(value) - 1
    except (RedisError, RuntimeError, TypeError, ValueError):
        return None


async def _lookup_pin(
    provider_id: int, pool: str, session_key: str, valid_ids: set[int]
) -> int | None:
    """Return the live pinned key id for a session, or None if absent/stale/dead."""
    try:
        service = get_redis()
        redis_key = _state_key("pin", provider_id, pool, session_key)
        raw = await service.client.get(redis_key)
    except (RedisError, RuntimeError):
        return None
    if raw is None:
        return None
    try:
        key_id = int(raw)
    except (TypeError, ValueError):
        key_id = -1
    if key_id not in valid_ids:
        with suppress(RedisError):
            await service.client.delete(redis_key)
        return None
    try:
        await service.client.expire(redis_key, _PIN_TTL_SECONDS)
    except RedisError:
        return None
    return key_id


async def _store_pin(provider_id: int, pool: str, session_key: str, key_id: int) -> int | None:
    try:
        service = get_redis()
        redis_key = _state_key("pin", provider_id, pool, session_key)
        stored = await service.client.set(
            redis_key,
            key_id,
            ex=_PIN_TTL_SECONDS,
            nx=True,
        )
        if stored:
            return key_id
        raw = await service.client.get(redis_key)
        return int(raw) if raw is not None else None
    except (RedisError, RuntimeError):
        return None
    except (TypeError, ValueError):
        return None


async def reset_selection_state() -> None:
    """Clear all Redis-backed round-robin cursors and session pins (tests)."""
    try:
        service = get_redis()
        keys = [key async for key in service.client.scan_iter(match=service.key("selector", "*"))]
        if keys:
            await service.client.delete(*keys)
    except (RedisError, RuntimeError):
        pass


def _lru_key(last_used: dt.datetime | None) -> dt.datetime:
    if last_used is None:
        return _EPOCH
    if last_used.tzinfo is None:
        return last_used.replace(tzinfo=dt.UTC)
    return last_used


def _manual_order(candidates: list[ApiKey]) -> list[ApiKey]:
    """Candidates in the operator's drag-sorted order (lowest ``sort_order`` first)."""
    return sorted(candidates, key=lambda k: (k.sort_order or 0, k.id or 0))


async def _rotate(ordered: list[ApiKey], provider_id: int, pool: str) -> list[ApiKey]:
    """Manual order rotated so a different key leads each request (round-robin)."""
    if len(ordered) <= 1:
        return ordered
    cursor = await _next_cursor(provider_id, pool)
    if cursor is None:
        return ordered
    start = cursor % len(ordered)
    return ordered[start:] + ordered[:start]


def _lead_with(ordered: list[ApiKey], key_id: int) -> list[ApiKey]:
    """Move the key with ``key_id`` to the front, keeping the rest in order."""
    lead = [k for k in ordered if k.id == key_id]
    rest = [k for k in ordered if k.id != key_id]
    return lead + rest


async def _apply_mode(
    provider: Provider,
    candidates: list[ApiKey],
    *,
    pool: str,
    session_key: str | None,
) -> list[ApiKey]:
    """Apply the provider's key-select mode to a single candidate list.

    The returned list is a try order; the dispatcher walks it from the front and
    falls back through the remainder on any failure, so "unless the key is
    unavailable" is handled for free for every mode.
    """
    if len(candidates) <= 1:
        return candidates

    mode = provider.key_select_mode or KeySelectMode.ROUND_ROBIN.value
    provider_id = provider.id or 0
    manual = _manual_order(candidates)

    if mode == KeySelectMode.FALLBACK.value:
        return manual
    if mode == KeySelectMode.RANDOM.value:
        shuffled = list(manual)
        random.shuffle(shuffled)
        return shuffled
    if mode == KeySelectMode.ROUND_ROBIN.value:
        return await _rotate(manual, provider_id, pool)

    pinned = mode in (
        KeySelectMode.PINNED_ROUND_ROBIN.value,
        KeySelectMode.PINNED_RANDOM.value,
    )
    if pinned:
        valid_ids = {k.id for k in manual if k.id is not None}
        # Reuse a live pin when this session already has one.
        if session_key is not None:
            existing = await _lookup_pin(provider_id, pool, session_key, valid_ids)
            if existing is not None:
                return _lead_with(manual, existing)
        # Assign a fresh pin via the mode's sub-strategy.
        if mode == KeySelectMode.PINNED_RANDOM.value:
            chosen = random.choice(manual)
        else:  # pinned round-robin
            chosen = (await _rotate(manual, provider_id, pool))[0]
        if session_key is not None and chosen.id is not None:
            pinned_id = await _store_pin(provider_id, pool, session_key, chosen.id)
            if pinned_id in valid_ids:
                return _lead_with(manual, pinned_id)
        return _lead_with(manual, chosen.id) if chosen.id is not None else manual

    # Unknown / legacy mode → round-robin.
    return await _rotate(manual, provider_id, pool)


async def _ordered_candidates(
    provider: Provider,
    active: list[ApiKey],
    recovered: list[ApiKey],
    *,
    pool: str,
    session_key: str | None,
) -> list[ApiKey]:
    """Full per-request try order: healthy keys first, recovered ones last.

    Active keys are ordered by the provider's key-select mode. Keys that recovered
    from a rate limit are *always* appended after them — they are a last resort,
    so a request burns through every healthy key before re-touching one that was
    recently 429'd. Recovered keys are themselves ordered by who has been free
    longest.
    """
    ordered = await _apply_mode(provider, active, pool=pool, session_key=session_key)
    if recovered:
        recovered = sorted(
            recovered,
            key=lambda k: (_lru_key(k.rate_limit_until), k.sort_order or 0, k.id or 0),
        )
        ordered = ordered + recovered
    return ordered


def _rate_limited_eligible(k: ApiKey, now: dt.datetime, recovery_seconds: int) -> bool:
    """Whether a rate-limited key may re-enter the pool now.

    Prefers the per-key ``rate_limit_until`` (set from ``Retry-After`` / the
    provider cooldown). Falls back to the legacy ``disabled_since +
    rate_limit_recovery_seconds`` window for rows parked before this field existed.
    """
    if k.status != KeyStatus.RATE_LIMITED.value:
        return False
    until = k.rate_limit_until
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt.UTC)
        return now >= until
    if recovery_seconds <= 0 or k.disabled_since is None:
        return False
    disabled_since = k.disabled_since
    if disabled_since.tzinfo is None:
        disabled_since = disabled_since.replace(tzinfo=dt.UTC)
    return (now - disabled_since).total_seconds() >= recovery_seconds


async def select_keys(
    provider: Provider,
    pool: str = "",
    rate_limit_recovery_seconds: int = 0,
    *,
    session_key: str | None = None,
    ignore_cooldown: bool = False,
) -> list[ApiKey]:
    """Per-request key try order for a provider, honouring its key-select mode.

    When ``pool`` is non-empty, only keys carrying that pool tag are used (so a
    route entry can target e.g. just the "leaked" or "members" keys). An empty
    pool uses every active key regardless of tag.

    A rate-limited key is **excluded from the pool entirely** until its cooldown
    elapses (``rate_limit_until``, set from the upstream ``Retry-After`` header or
    the provider/global cooldown). Once eligible again it is ranked *after* every
    active key, so healthy keys are always tried first. When ``ignore_cooldown``
    is true, currently rate-limited keys are appended as a final fallback. The
    dispatcher enables this only for a cooled upstream restored by the route's
    explicit all-cooled policy.
    """
    now = _utcnow()
    active: list[ApiKey] = []
    recovered: list[ApiKey] = []
    for k in provider.keys:
        if k.status == KeyStatus.ACTIVE.value:
            active.append(k)
        elif _rate_limited_eligible(k, now, rate_limit_recovery_seconds) or (
            ignore_cooldown and k.status == KeyStatus.RATE_LIMITED.value
        ):
            recovered.append(k)
    if pool:
        active = [k for k in active if (k.pool or "") == pool]
        recovered = [k for k in recovered if (k.pool or "") == pool]

    return await _ordered_candidates(
        provider, active, recovered, pool=pool, session_key=session_key
    )


# Process HTTP(S) proxy env vars consulted (in order) when proxy switching is
# off and no explicit static proxy URL is configured.
_ENV_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


def _env_proxy_url() -> str | None:
    for var in _ENV_PROXY_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return None


def static_routes(static_proxy_url: str) -> list[tuple[Route, Any | None]]:
    """The single fixed outbound route used when proxy switching is disabled.

    Uses ``static_proxy_url`` when set; otherwise falls back to the process
    HTTP(S)_PROXY/ALL_PROXY env vars, and finally a direct connection. The node
    element is always ``None`` so the dispatcher never disables a DB node on
    failure (there is nothing to rotate to).
    """
    url = (static_proxy_url or "").strip() or _env_proxy_url()
    return [(Route(proxy_url=url or None), None)]
