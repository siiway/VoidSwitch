"""Dynamic health ranking and platform-wide cooldowns for model upstreams."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import random
import time
from contextlib import suppress
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import UpstreamRankAlgorithm, UpstreamSelectMode
from voidswitch.core.redis import get_redis
from voidswitch.models.db import Provider, RouteUpstream, UpstreamCooldown
from voidswitch.services import settings_store

UpstreamKey = tuple[int, str, str]


@dataclass(slots=True)
class Stat:
    success_ewma: float = 1.0
    ttft_ewma_ms: float | None = None
    samples: int = 0
    consecutive_failures: int = 0
    updated: float = 0.0


@dataclass(slots=True)
class Ranked:
    upstream: Any
    key: UpstreamKey
    score: float
    tier: int
    success_rate: float
    ttft_ms: float | None
    samples: int
    consecutive_failures: float
    cooldown: UpstreamCooldown | None = None


_subscribers: set[asyncio.Queue[None]] = set()
_ALPHA = 0.2
_PIN_TTL = 3600
_STAT_TTL = 86400

_RECORD_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'success', 'ttft', 'samples', 'failures')
local success = tonumber(values[1]) or 1.0
local ttft = tonumber(values[2])
local samples = tonumber(values[3]) or 0
local failures = tonumber(values[4]) or 0
local target = tonumber(ARGV[1])
local alpha = tonumber(ARGV[3])
success = success + alpha * (target - success)
if target == 1 then failures = 0 else failures = failures + 1 end
if target == 1 and ARGV[2] ~= '' then
  local sample_ttft = tonumber(ARGV[2])
  if ttft then ttft = ttft + alpha * (sample_ttft - ttft) else ttft = sample_ttft end
end
redis.call('HSET', KEYS[1], 'success', success, 'samples', samples + 1,
  'failures', failures, 'updated', ARGV[4])
if ttft then redis.call('HSET', KEYS[1], 'ttft', ttft) end
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


def key_for(provider_id: int, model: str, pool: str = "") -> UpstreamKey:
    return provider_id, model, pool


def _notify() -> None:
    for queue in tuple(_subscribers):
        if queue.empty():
            queue.put_nowait(None)


def subscribe() -> asyncio.Queue[None]:
    queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[None]) -> None:
    _subscribers.discard(queue)


def _key_digest(key: UpstreamKey) -> str:
    return hashlib.sha256(f"{key[0]}\0{key[1]}\0{key[2]}".encode()).hexdigest()


def _stat_key(key: UpstreamKey) -> str:
    return get_redis().key("upstream-health", "stat", _key_digest(key))


def _pin_key(route_id: int, session_key: str) -> str:
    digest = hashlib.sha256(session_key.encode()).hexdigest()
    return get_redis().key("upstream-health", "pin", route_id, digest)


async def record(key: UpstreamKey, *, success: bool, ttft_ms: float | None = None) -> None:
    try:
        service = get_redis()
        await service.client.eval(
            _RECORD_SCRIPT,
            1,
            _stat_key(key),
            1 if success else 0,
            "" if ttft_ms is None else ttft_ms,
            _ALPHA,
            time.time(),
            _STAT_TTL,
        )
    except (RedisError, RuntimeError):
        return
    _notify()


async def reset_state() -> None:
    try:
        service = get_redis()
        keys = [
            key async for key in service.client.scan_iter(match=service.key("upstream-health", "*"))
        ]
        if keys:
            await service.client.delete(*keys)
    except (RedisError, RuntimeError):
        pass


def parse_retry_delay(
    headers: dict[str, str] | None, names: list[str]
) -> tuple[float | None, str | None]:
    if not headers:
        return None, None
    lower = {k.lower(): str(v).strip() for k, v in headers.items()}
    now = dt.datetime.now(dt.UTC)
    for name in names:
        raw = lower.get(name.lower())
        if not raw:
            continue
        try:
            value = float(raw)
            if value > 1_000_000_000:
                value -= now.timestamp()
            return max(0.0, value), name.lower()
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=dt.UTC)
                return max(0.0, (when - now).total_seconds()), name.lower()
            except (TypeError, ValueError):
                continue
    return None, None


async def load_cooldowns(
    session: AsyncSession, keys: set[UpstreamKey]
) -> dict[UpstreamKey, UpstreamCooldown]:
    if not keys:
        return {}
    provider_ids = {key[0] for key in keys}
    rows = (
        (
            await session.execute(
                select(UpstreamCooldown).where(UpstreamCooldown.provider_id.in_(provider_ids))
            )
        )
        .scalars()
        .all()
    )
    return {
        (r.provider_id, r.upstream_model, r.key_pool): r
        for r in rows
        if (r.provider_id, r.upstream_model, r.key_pool) in keys
    }


async def trip(
    session: AsyncSession,
    key: UpstreamKey,
    *,
    status_code: int,
    headers: dict[str, str] | None,
    provider: Provider,
    upstream: RouteUpstream | None = None,
    reason: str = "upstream failure",
) -> UpstreamCooldown | None:
    codes = list(upstream.cooldown_status_codes or []) if upstream else []
    codes = (
        codes
        or list(provider.upstream_cooldown_status_codes or [])
        or settings_store.get_list("upstream_cooldown_status_codes")
    )
    if status_code not in {int(code) for code in codes}:
        return None
    names = list(provider.upstream_retry_after_headers or []) or settings_store.get_list(
        "upstream_retry_after_headers"
    )
    retry, header = parse_retry_delay(headers, [str(name) for name in names])
    row = (
        await session.execute(
            select(UpstreamCooldown).where(
                UpstreamCooldown.provider_id == key[0],
                UpstreamCooldown.upstream_model == key[1],
                UpstreamCooldown.key_pool == key[2],
            )
        )
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.UTC)
    if row is None:
        row = UpstreamCooldown(
            provider_id=key[0],
            upstream_model=key[1],
            key_pool=key[2],
            until=now,
            consecutive_trips=0,
        )
        session.add(row)
    base = (
        (upstream.cooldown_seconds if upstream else 0)
        or provider.upstream_cooldown_seconds
        or settings_store.get_int("upstream_cooldown_seconds", 180)
    )
    if retry is None:
        cap = max(0, settings_store.get_int("upstream_cooldown_backoff_cap", 3))
        seconds = float(base) * (2 ** min(row.consecutive_trips or 0, cap))
        source = (
            "route"
            if upstream and upstream.cooldown_seconds
            else "provider"
            if provider.upstream_cooldown_seconds
            else "global"
        )
    else:
        seconds, source = retry, "retry_after" if header == "retry-after" else "header"
    maximum = settings_store.get_int("rate_limit_max_cooldown_seconds", 3600)
    if maximum > 0:
        seconds = min(seconds, maximum)
    row.until = now + dt.timedelta(seconds=max(0.0, seconds))
    row.reason = reason
    row.trigger_status = status_code
    row.trigger_source = source
    row.triggered_at = now
    row.consecutive_trips = (row.consecutive_trips or 0) + 1
    await session.flush()
    _notify()
    return row


async def reward(session: AsyncSession, key: UpstreamKey) -> None:
    row = (
        await session.execute(
            select(UpstreamCooldown).where(
                UpstreamCooldown.provider_id == key[0],
                UpstreamCooldown.upstream_model == key[1],
                UpstreamCooldown.key_pool == key[2],
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        now = dt.datetime.now(dt.UTC)
        row.until = now
        row.consecutive_trips = 0
        row.last_success_at = now
        await session.flush()


async def _load_stats(keys: list[UpstreamKey]) -> dict[UpstreamKey, Stat]:
    if not keys:
        return {}
    try:
        service = get_redis()
        pipe = service.client.pipeline(transaction=False)
        for key in keys:
            pipe.hgetall(_stat_key(key))
        raw_rows = await pipe.execute()
    except (RedisError, RuntimeError):
        return {}
    result: dict[UpstreamKey, Stat] = {}
    for key, raw in zip(keys, raw_rows, strict=True):
        if not raw:
            continue
        try:
            result[key] = Stat(
                success_ewma=float(raw.get("success", 1.0)),
                ttft_ewma_ms=(float(raw["ttft"]) if raw.get("ttft") else None),
                samples=int(raw.get("samples", 0)),
                consecutive_failures=int(raw.get("failures", 0)),
                updated=float(raw.get("updated", 0.0)),
            )
        except (TypeError, ValueError):
            continue
    return result


def _effective(stat: Stat | None, baseline: float | None) -> tuple[float, float | None, float, int]:
    if stat is None:
        return 1.0, baseline, 0.0, 0
    half = max(1, settings_store.get_int("upstream_ewma_half_life_seconds", 600))
    decay = 0.5 ** (max(0.0, time.time() - stat.updated) / half)
    success = 1.0 - (1.0 - stat.success_ewma) * decay
    if stat.ttft_ewma_ms is None:
        ttft = baseline
    elif baseline is None:
        ttft = stat.ttft_ewma_ms
    else:
        ttft = baseline + (stat.ttft_ewma_ms - baseline) * decay
    return success, ttft, stat.consecutive_failures * decay, stat.samples


async def rank(
    route: Any,
    cooldowns: dict[UpstreamKey, UpstreamCooldown],
    *,
    session_key: str | None = None,
    now: dt.datetime | None = None,
    rng: random.Random | None = None,
) -> tuple[list[Ranked], bool]:
    now = now or dt.datetime.now(dt.UTC)
    randomizer = rng or random.Random()
    candidates = [
        u for u in route.upstreams if u.enabled and u.provider is not None and u.provider.enabled
    ]
    candidate_keys = [key_for(u.provider_id, u.upstream_model, u.key_pool) for u in candidates]
    stats = await _load_stats(candidate_keys)
    ttfts = [s.ttft_ewma_ms for s in stats.values() if s.ttft_ewma_ms is not None]
    baseline = float(median(ttfts)) if ttfts else None
    minimum = max(1, settings_store.get_int("upstream_min_samples", 10))
    healthy = settings_store.get_float("upstream_tier_healthy_threshold", 0.9)
    rows: list[Ranked] = []
    cooling: list[Ranked] = []
    for u in candidates:
        key = key_for(u.provider_id, u.upstream_model, u.key_pool)
        success, ttft, failures, samples = _effective(stats.get(key), baseline)
        confidence = min(1.0, samples / minimum)
        score = (
            settings_store.get_float("upstream_rank_alpha", 100.0) * (1.0 - success) * confidence
            + settings_store.get_float("upstream_rank_beta", 1.0) * ((ttft or 0.0) / 1000.0)
            + settings_store.get_float("upstream_rank_gamma", 10.0) * failures
        )
        cooldown = cooldowns.get(key)
        active_cooldown = (
            cooldown is not None
            and cooldown.until.replace(tzinfo=cooldown.until.tzinfo or dt.UTC) > now
        )
        tier = 1 if samples < minimum else 0 if success >= healthy else 2
        row = Ranked(
            u,
            key,
            score,
            3 if active_cooldown else tier,
            success,
            ttft,
            samples,
            failures,
            cooldown,
        )
        (cooling if active_cooldown else rows).append(row)
    ignored = False
    behavior = route.upstream_all_cooled_behavior or settings_store.get_str(
        "upstream_all_cooled_behavior", "ignore_cooldown"
    )
    if cooling and behavior == "ignore_cooldown":
        # Keep cooled candidates behind normal candidates as a last-resort
        # fallback. A normal candidate may have no eligible key or outbound route;
        # treating its mere presence as availability previously discarded every
        # cooled-but-usable provider and produced attempts=0.
        rows.extend(cooling)
        ignored = True
    algorithm = route.upstream_rank_algorithm or settings_store.get_str(
        "upstream_rank_algorithm", "weighted"
    )

    def sort_group(group_rows: list[Ranked]) -> list[Ranked]:
        group_rows.sort(
            key=lambda r: (
                r.tier == 3,
                (r.tier if algorithm == UpstreamRankAlgorithm.TIERED.value else 0),
                r.score,
                -(r.upstream.weight or 1),
                r.upstream.position,
                r.upstream.id or 0,
            )
        )
        return group_rows

    grouped: dict[int, list[Ranked]] = {}
    for row in rows:
        grouped.setdefault(max(0, row.upstream.group_position), []).append(row)
    rows = [row for group in sorted(grouped) for row in sort_group(grouped[group])]
    if not rows:
        return [], ignored
    mode = route.upstream_select_mode or settings_store.get_str("upstream_select_mode", "best")
    first_group = max(0, rows[0].upstream.group_position)
    selectable = [row for row in rows if max(0, row.upstream.group_position) == first_group]
    if mode.startswith("pinned_") and session_key:
        existing: int | None = None
        try:
            service = get_redis()
            redis_pin_key = _pin_key(route.id or 0, session_key)
            raw = await service.client.get(redis_pin_key)
            existing = int(raw) if raw is not None else None
        except (RedisError, RuntimeError, TypeError, ValueError):
            existing = None
        if existing is not None:
            found = next((r for r in selectable if r.upstream.id == existing), None)
            if found and (found.tier != 3 or all(r.tier == 3 for r in selectable)):
                rows.remove(found)
                rows.insert(0, found)
                with suppress(RedisError):
                    await service.client.expire(redis_pin_key, _PIN_TTL)
                return rows, ignored
    if mode in (UpstreamSelectMode.BALANCED.value, UpstreamSelectMode.PINNED_BALANCED.value):
        tolerance = max(0.0, settings_store.get_float("upstream_balance_tolerance", 0.2))
        limit = selectable[0].score * (1 + tolerance) if selectable[0].score > 0 else tolerance
        pool = [r for r in selectable if r.tier != 3 and r.score <= limit]
        if not pool:
            pool = [r for r in selectable if r.score <= limit]
        chosen = randomizer.choices(
            pool, weights=[max(1, r.upstream.weight) / max(r.score, 0.001) for r in pool], k=1
        )[0]
        rows.remove(chosen)
        rows.insert(0, chosen)
    elif mode == UpstreamSelectMode.PINNED_BEST.value:
        jitter = max(0.0, settings_store.get_float("upstream_pin_jitter", 0.15))
        chosen = min(selectable, key=lambda r: r.score * (1 + randomizer.uniform(-jitter, jitter)))
        rows.remove(chosen)
        rows.insert(0, chosen)
    if mode.startswith("pinned_") and session_key and rows[0].upstream.id is not None:
        try:
            service = get_redis()
            redis_pin_key = _pin_key(route.id or 0, session_key)
            stored = await service.client.set(
                redis_pin_key, rows[0].upstream.id, ex=_PIN_TTL, nx=True
            )
            if not stored:
                raw = await service.client.get(redis_pin_key)
                pinned_id = int(raw) if raw is not None else None
                found = next((r for r in selectable if r.upstream.id == pinned_id), None)
                if found and (found.tier != 3 or all(r.tier == 3 for r in selectable)):
                    rows.remove(found)
                    rows.insert(0, found)
        except (RedisError, RuntimeError):
            pass
        except (TypeError, ValueError):
            pass
    return rows, ignored


def status_for(row: Ranked) -> str:
    if row.tier == 3:
        return "unavailable"
    if row.samples < settings_store.get_int("upstream_min_samples", 10):
        return "learning"
    return (
        "healthy"
        if row.success_rate >= settings_store.get_float("upstream_tier_healthy_threshold", 0.9)
        else "degraded"
    )
