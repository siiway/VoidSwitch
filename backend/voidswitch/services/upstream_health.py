"""Dynamic health ranking and platform-wide cooldowns for model upstreams."""

from __future__ import annotations

import asyncio
import datetime as dt
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import UpstreamRankAlgorithm, UpstreamSelectMode
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


_stats: dict[UpstreamKey, Stat] = {}
_pins: dict[tuple[int, str], tuple[int, float]] = {}
_subscribers: set[asyncio.Queue[None]] = set()
_ALPHA = 0.2
_PIN_TTL = 3600.0


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


def record(key: UpstreamKey, *, success: bool, ttft_ms: float | None = None) -> None:
    stat = _stats.setdefault(key, Stat(updated=time.monotonic()))
    target = 1.0 if success else 0.0
    stat.success_ewma += _ALPHA * (target - stat.success_ewma)
    stat.samples += 1
    stat.consecutive_failures = 0 if success else stat.consecutive_failures + 1
    if success and ttft_ms is not None:
        stat.ttft_ewma_ms = (
            ttft_ms
            if stat.ttft_ewma_ms is None
            else stat.ttft_ewma_ms + _ALPHA * (ttft_ms - stat.ttft_ewma_ms)
        )
    stat.updated = time.monotonic()
    _notify()


def reset_state() -> None:
    _stats.clear()
    _pins.clear()


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


def _effective(key: UpstreamKey, baseline: float | None) -> tuple[float, float | None, float, int]:
    stat = _stats.get(key)
    if stat is None:
        return 1.0, baseline, 0.0, 0
    half = max(1, settings_store.get_int("upstream_ewma_half_life_seconds", 600))
    decay = 0.5 ** ((time.monotonic() - stat.updated) / half)
    success = 1.0 - (1.0 - stat.success_ewma) * decay
    if stat.ttft_ewma_ms is None:
        ttft = baseline
    elif baseline is None:
        ttft = stat.ttft_ewma_ms
    else:
        ttft = baseline + (stat.ttft_ewma_ms - baseline) * decay
    return success, ttft, stat.consecutive_failures * decay, stat.samples


def rank(
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
    ttfts = [
        s.ttft_ewma_ms
        for u in candidates
        if (s := _stats.get(key_for(u.provider_id, u.upstream_model, u.key_pool)))
        and s.ttft_ewma_ms is not None
    ]
    baseline = float(median(ttfts)) if ttfts else None
    minimum = max(1, settings_store.get_int("upstream_min_samples", 10))
    healthy = settings_store.get_float("upstream_tier_healthy_threshold", 0.9)
    rows: list[Ranked] = []
    cooling: list[Ranked] = []
    for u in candidates:
        key = key_for(u.provider_id, u.upstream_model, u.key_pool)
        success, ttft, failures, samples = _effective(key, baseline)
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
    if not rows and cooling and behavior == "ignore_cooldown":
        rows, ignored = cooling, True
    algorithm = route.upstream_rank_algorithm or settings_store.get_str(
        "upstream_rank_algorithm", "weighted"
    )
    rows.sort(
        key=lambda r: (
            (r.tier if algorithm == UpstreamRankAlgorithm.TIERED.value else 0),
            r.score,
            -(r.upstream.weight or 1),
            r.upstream.position,
            r.upstream.id or 0,
        )
    )
    if not rows:
        return [], ignored
    mode = route.upstream_select_mode or settings_store.get_str("upstream_select_mode", "best")
    pin_key = (route.id or 0, session_key or "")
    if mode.startswith("pinned_") and session_key:
        existing = _pins.get(pin_key)
        if existing and time.monotonic() - existing[1] <= _PIN_TTL:
            found = next((r for r in rows if r.upstream.id == existing[0]), None)
            if found:
                rows.remove(found)
                rows.insert(0, found)
                _pins[pin_key] = (existing[0], time.monotonic())
                return rows, ignored
    if mode in (UpstreamSelectMode.BALANCED.value, UpstreamSelectMode.PINNED_BALANCED.value):
        tolerance = max(0.0, settings_store.get_float("upstream_balance_tolerance", 0.2))
        limit = rows[0].score * (1 + tolerance) if rows[0].score > 0 else tolerance
        pool = [r for r in rows if r.score <= limit]
        chosen = randomizer.choices(
            pool, weights=[max(1, r.upstream.weight) / max(r.score, 0.001) for r in pool], k=1
        )[0]
        rows.remove(chosen)
        rows.insert(0, chosen)
    elif mode == UpstreamSelectMode.PINNED_BEST.value:
        jitter = max(0.0, settings_store.get_float("upstream_pin_jitter", 0.15))
        chosen = min(rows, key=lambda r: r.score * (1 + randomizer.uniform(-jitter, jitter)))
        rows.remove(chosen)
        rows.insert(0, chosen)
    if mode.startswith("pinned_") and session_key and rows[0].upstream.id is not None:
        _pins[pin_key] = (rows[0].upstream.id, time.monotonic())
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
