"""The resilient proxy/failover engine.

A request is tried across the cartesian space of (provider, key, route) until one
succeeds or the retry budget is exhausted:

* **Network / timeout error** → blame the *proxy*: bump its ``failed_count``,
  disable it past the threshold, keep the key, retry on the next route.
* **Auth / balance error**     → blame the *key*: disable it immediately and
  retry with a fresh key (or the next provider).
* **Rate limit / 5xx**         → transient: rotate to the next key/provider.
* **4xx client error**         → the caller's request is wrong; return as-is.

Streaming and non-streaming are both supported. Failover only happens before the
first byte of a streamed response is committed to the client (standard for
streaming proxies).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import re
import time
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import ApiStyle, KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger, redact_headers
from voidswitch.models.db import ApiKey, ExposedModel, Node, Provider, RequestLog
from voidswitch.services import model_routing, routing, settings_store, transform, usage_rollup
from voidswitch.services.network import Route, get_pool
from voidswitch.services.providers.base import BaseProvider, ErrorClass
from voidswitch.services.providers.registry import get_adapter
from voidswitch.services.selector import select_keys, static_routes

log = get_logger("dispatcher")

_PASSTHROUGH_RE = re.compile(
    r"^(?P<exposed>[^\s@]+?)(?:\s*=>\s*(?P<upstream>[^\s@]+?))?(?:\s*@\s*(?P<pool>\S+))?$"
)


def _parse_passthrough_entry(entry: str) -> dict[str, str]:
    """Parse a passthrough whitelist entry into its components."""
    m = _PASSTHROUGH_RE.match(entry.strip())
    if m is None:
        return {"exposed": entry.strip(), "upstream": entry.strip(), "pool": ""}
    exposed = (m.group("exposed") or "").strip()
    upstream = (m.group("upstream") or exposed).strip()
    pool = (m.group("pool") or "").strip()
    return {"exposed": exposed, "upstream": upstream, "pool": pool}


_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)

# PoolTimeout means the connection pool was exhausted — this is a gateway
# capacity/concurrency issue, NOT a proxy fault. Treating it as a proxy failure
# cascades: fewer proxies → more PoolTimeouts → more disabled proxies → collapse.
_POOL_TIMEOUT_ERRORS = (httpx.PoolTimeout,)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stringify(value: Any) -> str:
    """Stable string form of a payload fragment for session hashing."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


# ``request_logs.session_id`` is VARCHAR(255); the client-controlled session id is
# unbounded, so cap it here — otherwise an oversized ``x-voidswitch-session``
# header overflows the column on PostgreSQL and 500s the request (the upstream
# has already been paid for at that point).
_MAX_SESSION_ID_CHARS = 240


def _session_key(req: DispatchRequest) -> str:
    """A stable identifier for the conversation/session behind a request.

    Used by the per-session pinned key-select modes so the same session keeps
    hitting the same upstream key. Precedence:

    1. An explicit client-supplied session id (``x-voidswitch-session``; the
       OpenCode plugin forwards its native ``sessionID``) — the most reliable.
    2. An Anthropic ``metadata.user_id`` tag.
    3. A hash of the conversation prefix — the system prompt plus the first
       message — which stays constant across the turns of one session.

    Always namespaced by the calling Void-Token so two tokens never share a pin.
    """
    if req.session_id:
        sid = req.session_id[:_MAX_SESSION_ID_CHARS]
        return f"t{req.token_id}:sid:{sid}"
    payload = req.payload or {}
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        uid = meta.get("user_id")
        if isinstance(uid, str) and uid:
            return f"t{req.token_id}:u:{uid[:_MAX_SESSION_ID_CHARS]}"
    parts: list[str] = []
    # ``system``/``messages`` (OpenAI-chat & Anthropic) or ``instructions``/``input``
    # (OpenAI Responses) — whichever the inbound dialect carries.
    system = payload.get("system")
    if system is None:
        system = payload.get("instructions")
    if system is not None:
        parts.append(_stringify(system))
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        parts.append(_stringify(messages[0]))
    else:
        raw_input = payload.get("input")
        if isinstance(raw_input, str) and raw_input:
            parts.append(raw_input)
        elif isinstance(raw_input, list) and raw_input:
            parts.append(_stringify(raw_input[0]))
    seed = "\x00".join(parts)
    digest = hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest()[:16]
    return f"t{req.token_id}:s:{digest}"


@dataclass(slots=True)
class DispatchRequest:
    inbound_style: ApiStyle
    model: str
    payload: dict[str, Any]
    stream: bool
    token_id: int | None = None
    user_sub: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    client_type: str | None = None
    is_opencode: bool = False
    debug_enabled: bool = False
    passthrough_headers: dict[str, str] = field(default_factory=dict)
    # Client-supplied stable session id (e.g. the OpenCode plugin's sessionID).
    # Authoritative for the per-session pinned key-select modes when present.
    session_id: str | None = None


@dataclass(slots=True)
class DispatchResult:
    status_code: int
    is_stream: bool
    media_type: str = "application/json"
    content: bytes | None = None
    stream: AsyncIterator[bytes] | None = None
    provider_name: str | None = None
    upstream_style: str | None = None
    model: str | None = None
    attempts: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# Translation routing
# --------------------------------------------------------------------------- #


# OpenAI Chat Completions is the canonical hub: every cross-style conversion
# pivots through it, so any pair of the three dialects is bridged by composing at
# most two direct conversions (see services.transform).


def _request_to_openai(style: ApiStyle, payload: dict) -> dict:
    if style is ApiStyle.ANTHROPIC:
        return transform.anthropic_request_to_openai(payload)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.responses_request_to_openai(payload)
    return payload


def _request_from_openai(style: ApiStyle, payload: dict) -> dict:
    if style is ApiStyle.ANTHROPIC:
        return transform.openai_request_to_anthropic(payload)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.openai_request_to_responses(payload)
    return payload


def _translate_request(inbound: ApiStyle, upstream: ApiStyle, payload: dict) -> dict:
    if inbound == upstream:
        return payload
    return _request_from_openai(upstream, _request_to_openai(inbound, payload))


def _response_to_openai(style: ApiStyle, body: dict, model: str) -> dict:
    if style is ApiStyle.ANTHROPIC:
        return transform.anthropic_response_to_openai(body, model=model)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.responses_response_to_openai(body, model=model)
    return body


def _response_from_openai(style: ApiStyle, body: dict, model: str) -> dict:
    if style is ApiStyle.ANTHROPIC:
        return transform.openai_response_to_anthropic(body, model=model)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.openai_response_to_responses(body, model=model)
    return body


def _translate_response(inbound: ApiStyle, upstream: ApiStyle, body: dict, model: str) -> dict:
    if inbound == upstream:
        return body
    return _response_from_openai(inbound, _response_to_openai(upstream, body, model), model)


def _stream_to_openai(
    style: ApiStyle, byte_iter: AsyncIterator[bytes], model: str
) -> AsyncIterator[bytes]:
    if style is ApiStyle.ANTHROPIC:
        return transform.anthropic_stream_to_openai(byte_iter, model=model)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.responses_stream_to_openai(byte_iter, model=model)
    return byte_iter


def _stream_from_openai(
    style: ApiStyle, byte_iter: AsyncIterator[bytes], model: str
) -> AsyncIterator[bytes]:
    if style is ApiStyle.ANTHROPIC:
        return transform.openai_stream_to_anthropic(byte_iter, model=model)
    if style is ApiStyle.OPENAI_RESPONSES:
        return transform.openai_stream_to_responses(byte_iter, model=model)
    return byte_iter


def _translate_stream(
    inbound: ApiStyle, upstream: ApiStyle, byte_iter: AsyncIterator[bytes], model: str
) -> AsyncIterator[bytes]:
    if inbound == upstream:
        return byte_iter
    return _stream_from_openai(inbound, _stream_to_openai(upstream, byte_iter, model), model)


# --------------------------------------------------------------------------- #
# Error payloads in the client's dialect
# --------------------------------------------------------------------------- #


def _error_body(style: ApiStyle, message: str, err_type: str = "upstream_error") -> bytes:
    if style is ApiStyle.ANTHROPIC:
        payload = {"type": "error", "error": {"type": err_type, "message": message}}
    else:
        payload = {"error": {"message": message, "type": err_type, "code": err_type}}
    return json.dumps(payload).encode()


# --------------------------------------------------------------------------- #
# State mutation helpers
# --------------------------------------------------------------------------- #


def _disable_key(key: ApiKey, status: KeyStatus, reason: str) -> None:
    key.status = status.value
    key.disabled_reason = reason
    key.last_checked_at = _utcnow()
    if key.disabled_since is None:
        key.disabled_since = _utcnow()


def _parse_retry_after(headers: dict[str, str] | None) -> float | None:
    """Seconds to wait from a ``Retry-After`` response header, per RFC 9110.

    The value is either a non-negative integer count of seconds (delta-seconds)
    or an HTTP-date; both forms are accepted. Returns ``None`` when the header is
    absent or unparseable, so the caller can fall back to a configured cooldown.
    """
    if not headers:
        return None
    # Header names from httpx are case-insensitive-ish; normalise to be safe.
    raw = None
    for k, v in headers.items():
        if k.lower() == "retry-after":
            raw = v
            break
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    # delta-seconds form.
    try:
        secs = float(raw)
        return secs if secs >= 0 else None
    except ValueError:
        pass
    # HTTP-date form.
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    delta = (when - _utcnow()).total_seconds()
    return delta if delta > 0 else 0.0


def _mark_rate_limited(
    key: ApiKey,
    *,
    retry_after: float | None,
    provider_cooldown: int,
    global_cooldown: int,
    max_cooldown: int,
) -> float:
    """Park a 429'd key out of the pool until it may be retried.

    Cooldown precedence: the upstream's ``Retry-After`` header → the provider's
    configured cooldown → the global ``rate_limit_recovery_seconds`` setting. The
    result is clamped to ``max_cooldown`` (0 = uncapped) so a key is never parked
    indefinitely. Returns the cooldown actually applied (seconds).
    """
    if retry_after is not None:
        cooldown = retry_after
    elif provider_cooldown > 0:
        cooldown = float(provider_cooldown)
    else:
        cooldown = float(global_cooldown)
    cooldown = max(0.0, cooldown)
    if max_cooldown > 0:
        cooldown = min(cooldown, float(max_cooldown))
    now = _utcnow()
    key.status = KeyStatus.RATE_LIMITED.value
    key.last_checked_at = now
    if key.disabled_since is None:
        key.disabled_since = now
    key.rate_limit_until = now + dt.timedelta(seconds=cooldown)
    if retry_after is not None:
        source = "retry-after"
    elif provider_cooldown > 0:
        source = "provider"
    else:
        source = "global"
    key.disabled_reason = f"HTTP 429 rate limited (retry in {int(cooldown)}s via {source})"
    return cooldown


def _reward_key(key: ApiKey) -> None:
    """Reset a rate-limited key to active when a request succeeds."""
    if key.status == KeyStatus.RATE_LIMITED.value:
        key.status = KeyStatus.ACTIVE.value
        key.failed_count = 0
        key.disabled_reason = None
        key.disabled_since = None
        key.rate_limit_until = None
        key.last_used_at = _utcnow()


# --------------------------------------------------------------------------- #
# Core dispatch
# --------------------------------------------------------------------------- #


async def dispatch(
    req: DispatchRequest,
    session: AsyncSession | None = None,
) -> DispatchResult:
    if session is None:
        db = get_database()
        async with db.session() as s:
            return await _do_dispatch(req, s)
    return await _do_dispatch(req, session)


async def _resolve_passthrough(
    session: AsyncSession, model: str
) -> tuple[Provider, str, str] | None:
    """If ``model`` is a passthrough ``provider-slug/exposed-model-id`` format,
    look up the provider, match the whitelist, and return
    ``(provider, upstream_model, key_pool)``.  Returns ``None`` when the model is
    not a passthrough (or the provider is not found / passthrough disabled / the
    model is not in the whitelist).
    """
    parts = model.split("/", 1)
    if len(parts) != 2:
        return None
    provider_slug, exposed_id = parts
    provider = (
        await session.execute(select(Provider).where(Provider.slug == provider_slug))
    ).scalar_one_or_none()
    if provider is None or not provider.passthrough_enabled:
        return None
    for entry in provider.passthrough_models or []:
        parsed = _parse_passthrough_entry(entry)
        if parsed["exposed"] == exposed_id:
            return provider, parsed["upstream"], parsed["pool"]
    return None


async def _do_dispatch(req: DispatchRequest, session: AsyncSession) -> DispatchResult:
    settings = get_settings()
    max_retries = max(1, settings_store.get_int("max_retries", 6))
    connect_timeout = float(settings_store.get_int("connect_timeout_seconds", 15))
    request_timeout = float(settings_store.get_int("request_timeout_seconds", 300))
    stream_idle = float(settings_store.get_int("stream_idle_timeout_seconds", 120))
    # Hard wall-clock cap on a single request (streaming included). When exceeded
    # the connection is force-cut and the log row marked ``terminated``.
    response_timeout = float(settings_store.get_int("response_timeout_seconds", 3600))
    rate_limit_recovery = settings_store.get_int("rate_limit_recovery_seconds", 180)
    rate_limit_max_cooldown = settings_store.get_int("rate_limit_max_cooldown_seconds", 3600)

    pool = get_pool()
    attempts = 0
    last_error = "no upstream available"
    last_status = 502
    session_key = _session_key(req)
    dispatch_started_at = _utcnow()

    # Per-attempt debug trail (only populated for debug-enabled tokens) and the
    # context of the most recent attempt — so that even a total failover
    # exhaustion is attributable to the provider / key / route / upstream model it
    # last tried (instead of a bare "provider —, route anthropic→?").
    debug_trail: list[dict[str, Any]] = []
    attempt_summaries: list[dict[str, Any]] = []
    last_ctx: dict[str, Any] = {}
    last_outcome: _Attempt | None = None

    # Passthrough models (``provider-slug/exposed-model-id``) bypass the exposed
    # model + route system and dispatch directly to the provider.
    passthrough = await _resolve_passthrough(session, req.model)
    if passthrough is not None:
        passthrough_provider, passthrough_upstream, passthrough_pool = passthrough
        if not passthrough_provider.enabled:
            return DispatchResult(
                status_code=404,
                is_stream=False,
                content=_error_body(
                    req.inbound_style,
                    f"Provider for '{req.model}' is disabled.",
                    "model_not_found",
                ),
                model=req.model,
            )
        layers = [
            SimpleNamespace(
                position=0,
                max_attempts=1,
                entries=[
                    SimpleNamespace(
                        provider=passthrough_provider,
                        upstream_model=passthrough_upstream,
                        key_pool=passthrough_pool,
                        enabled=True,
                        weight=1,
                    )
                ],
            )
        ]
    else:
        # The inbound model must be an *exposed* model; raw upstream ids
        # (``slug/model``) are never accepted here (rejected earlier by gateway).
        exposed = (
            await session.execute(select(ExposedModel).where(ExposedModel.model_id == req.model))
        ).scalar_one_or_none()
        if exposed is None:
            return DispatchResult(
                status_code=404,
                is_stream=False,
                content=_error_body(
                    req.inbound_style,
                    f"No exposed model '{req.model}'.",
                    "model_not_found",
                ),
                model=req.model,
            )

        route = await model_routing.resolve_route(session, exposed)
        if not route.layers:
            return DispatchResult(
                status_code=404,
                is_stream=False,
                content=_error_body(
                    req.inbound_style,
                    f"Model '{req.model}' has no route configured.",
                    "model_not_found",
                ),
                model=req.model,
            )
        layers = route.layers

    # Proxy switching off (external proxy like mihomo handles egress): every
    # request goes through a single fixed route and no node is ever disabled.
    proxy_switching = settings_store.get_bool("proxy_switching_enabled", True)
    # When node health-checking is off, connectivity is managed externally
    # (e.g. mihomo): a failing node is never auto-disabled, so failures are
    # counted but never park a node.
    node_health_check = settings_store.get_bool("proxy_health_check_enabled", True)
    fixed_routes = (
        None if proxy_switching else static_routes(settings_store.get_str("static_proxy_url", ""))
    )

    # Walk the flow: layers top→bottom are fallback pools; each layer tries up to
    # ``max_attempts`` entries (weighted-random order); within an entry, keys then
    # outbound nodes are iterated. The whole flow is capped by ``max_retries``.
    for layer in layers:
        if attempts >= max_retries:
            break
        entries = model_routing.weighted_entries(layer)  # ty: ignore[invalid-argument-type]
        layer_attempts = max(1, int(layer.max_attempts or 1))
        for entry in entries[:layer_attempts]:
            if attempts >= max_retries:
                break
            provider = entry.provider
            if provider is None or not provider.enabled:
                continue
            adapter = get_adapter(provider)
            upstream_model = entry.upstream_model or req.model
            key_pool = entry.key_pool or ""

            # Per-provider outbound routes — from its node group (or the default
            # group), unless proxy switching is disabled (single fixed route).
            if fixed_routes is not None:
                routes = fixed_routes
            else:
                group = await routing.provider_routes(session, provider)
                routes = await routing.group_routes(session, group)
            if not routes:
                last_error = f"provider '{provider.name}': no available outbound node"
                last_status = 502
                continue

            keys = select_keys(
                provider,
                key_pool,
                rate_limit_recovery_seconds=rate_limit_recovery,
                session_key=session_key,
            )
            upstream_style = adapter.style
            timeout_override = provider.timeout_seconds or 0
            read_timeout = float(timeout_override) if timeout_override else request_timeout

            secret_key = settings.server.secret_key

            for key in keys:
                if attempts >= max_retries:
                    break
                try:
                    plaintext = await _resolve_token(session, adapter, key, secret_key)
                except Exception as exc:
                    # A credential-resolution failure (e.g. a transient network blip
                    # while refreshing a Claude Code / xAI OAuth bundle) is NOT proof
                    # the key is invalid — permanently disabling it here would park a
                    # still-usable key until an operator intervenes. Record it and
                    # move to the next key.
                    last_error = f"credential resolve failed: {exc}"
                    last_status = 401
                    log.debug("credential_resolve_failed", key_id=key.id, error=str(exc))
                    continue  # next key
                url, headers, body = _prepare_body(
                    req,
                    adapter,
                    upstream_style,
                    upstream_model,
                    plaintext,
                )

                oauth_refreshed = False
                for route_hop, node in routes:
                    if attempts >= max_retries:
                        break
                    attempts += 1
                    outcome = await _attempt(
                        pool=pool,
                        adapter=adapter,
                        route=route_hop,
                        url=url,
                        headers=headers,
                        body=body,
                        stream=req.stream,
                        connect_timeout=connect_timeout,
                        read_timeout=stream_idle if req.stream else read_timeout,
                        # Non-streaming requests get the total response timeout as a
                        # hard cap (streams enforce it inside _build_stream).
                        total_timeout=response_timeout if not req.stream else None,
                        # Streamed requests through a zero-token-retry provider are
                        # spooled until the first real content token, so a degenerate
                        # empty 200 can be retried before anything reaches the client.
                        spool_first_content=bool(provider.retry_on_zero_token and req.stream),
                    )

                    # Remember this attempt for traceability + the debug trail.
                    last_outcome = outcome
                    last_ctx = {
                        "provider": provider,
                        "key": key,
                        "node": node,
                        "upstream_style": upstream_style,
                        "upstream_model": upstream_model,
                    }
                    # Always record a lightweight attempt summary (for the detail modal).
                    attempt_summaries.append(
                        _attempt_summary(
                            attempt=attempts,
                            provider=provider,
                            key=key,
                            adapter=adapter,
                            upstream_model=upstream_model,
                            outcome=outcome,
                        )
                    )
                    if req.debug_enabled:
                        debug_trail.append(
                            _trail_entry(
                                attempt=attempts,
                                provider=provider,
                                key=key,
                                adapter=adapter,
                                upstream_model=upstream_model,
                                outcome=outcome,
                            )
                        )

                    if outcome.network_error:
                        last_error = outcome.error or "network error"
                        last_status = 502
                        # PoolTimeout / total-response-timeout are capacity or
                        # wall-clock issues, NOT a node fault. Penalising the node
                        # for these cascades failures: fewer nodes → more timeouts →
                        # more disabled nodes → collapse.
                        if outcome.blame_proxy and node is not None:
                            routing.penalize_node(node, last_error, auto_disable=node_health_check)
                        await session.flush()
                        continue  # keep key, next node

                    # We have an HTTP response.
                    if node is not None:
                        routing.reward_node(node)
                    err_class = adapter.classify(outcome.status_code, outcome.body_json)
                    # A provider that can *detect* "no quota" (vs a plain rate
                    # limit) turns a 429 into a permanently-disabled key.
                    if err_class is ErrorClass.RATE_LIMITED and adapter.detect_no_quota(
                        outcome.status_code, outcome.body_json
                    ):
                        err_class = ErrorClass.INSUFFICIENT_BALANCE

                    if err_class is ErrorClass.OK:
                        # "200 OK + 0 tokens" auto-retry: a 200 that produced nothing
                        # usable is a degenerate upstream result. Detect it (usage 0
                        # for non-streaming, or a stream that ended before any real
                        # content) and retry the next key/provider — the empty reply
                        # is never delivered to the client.
                        degenerate = False
                        if provider.retry_on_zero_token:
                            total = _extract_usage(outcome.body_json, upstream_style)[
                                "total_tokens"
                            ]
                            degenerate = outcome.degenerate_empty if req.stream else total == 0
                        if degenerate:
                            last_error = "upstream returned 200 OK with 0 tokens"
                            last_status = 200
                            key.failed_count += 1
                            await session.flush()
                            break  # next key/provider
                        key.total_requests += 1
                        key.last_used_at = _utcnow()
                        if key.failed_count:
                            key.failed_count = 0
                        _reward_key(key)
                        return await _finalise_success(
                            session=session,
                            req=req,
                            provider=provider,
                            adapter=adapter,
                            key=key,
                            node=node,
                            outcome=outcome,
                            upstream_model=upstream_model,
                            attempts=attempts,
                            debug_attempts=debug_trail,
                            attempt_summaries=attempt_summaries,
                            started_at=dispatch_started_at,
                            response_timeout=response_timeout,
                        )

                    if err_class in (ErrorClass.KEY_INVALID, ErrorClass.INSUFFICIENT_BALANCE):
                        # Claude Code OAuth: a 401 usually means the access token
                        # expired — force-refresh and retry this key once before
                        # giving up on it (mirrors the CLI's 401 behaviour).
                        if (
                            err_class is ErrorClass.KEY_INVALID
                            and adapter.refresh_on_invalid_key
                            and not oauth_refreshed
                        ):
                            oauth_refreshed = True
                            try:
                                plaintext = await _resolve_token(
                                    session, adapter, key, secret_key, force_refresh=True
                                )
                                url, headers, body = _prepare_body(
                                    req,
                                    adapter,
                                    upstream_style,
                                    upstream_model,
                                    plaintext,
                                )
                                continue  # retry same key with the refreshed token
                            except Exception as exc:
                                last_error = f"oauth refresh failed: {exc}"
                        status = (
                            KeyStatus.INVALID
                            if err_class is ErrorClass.KEY_INVALID
                            else KeyStatus.INSUFFICIENT_BALANCE
                        )
                        _disable_key(key, status, f"HTTP {outcome.status_code}: {err_class}")
                        last_error = f"key disabled ({err_class})"
                        last_status = outcome.status_code
                        await session.flush()
                        break  # next key

                    if err_class is ErrorClass.RATE_LIMITED:
                        cooldown = _mark_rate_limited(
                            key,
                            retry_after=_parse_retry_after(outcome.resp_headers),
                            provider_cooldown=provider.rate_limit_cooldown_seconds or 0,
                            global_cooldown=rate_limit_recovery,
                            max_cooldown=rate_limit_max_cooldown,
                        )
                        last_error = f"rate limited (cooldown {int(cooldown)}s)"
                        last_status = 429
                        await session.flush()
                        break  # next key

                    if err_class is ErrorClass.NOT_FOUND:
                        # The upstream doesn't serve this model — a *routable*
                        # failure. Fall through to the next entry/pool instead of
                        # surfacing a 404 to the client.
                        last_error = (
                            f"upstream 404: model '{upstream_model}' not served by "
                            f"provider '{provider.name}'"
                        )
                        last_status = 404
                        await session.flush()
                        break  # next key (then next entry)

                    if err_class is ErrorClass.SERVER_ERROR:
                        key.failed_count += 1
                        last_error = f"upstream {outcome.status_code}"
                        last_status = outcome.status_code
                        await session.flush()
                        break  # next key/provider

                    # BAD_REQUEST: the client's request is wrong — return it as-is.
                    await _log_request(
                        session,
                        req,
                        provider=provider,
                        key=key,
                        node=node,
                        upstream_style=upstream_style,
                        upstream_model=upstream_model,
                        status_code=outcome.status_code,
                        success=False,
                        attempts=attempts,
                        error=f"client error {outcome.status_code}",
                        upstream_url=outcome.url,
                        req_method=outcome.req_method,
                        req_headers=outcome.req_headers,
                        resp_headers=outcome.resp_headers,
                        resp_body=_resp_body_repr(outcome),
                        debug_attempts=debug_trail,
                        attempt_summaries=attempt_summaries,
                        started_at=dispatch_started_at,
                        finished_at=_utcnow(),
                    )
                    return _passthrough_error(req, outcome, upstream_style)

    # Exhausted everything. Attribute the failure to the last provider / key /
    # node / upstream model actually tried (when any attempt happened) and, for
    # debug tokens, attach the last upstream response + the full per-attempt
    # trail — so an "upstream 500" is diagnosable instead of a bare provider "—".
    await _log_request(
        session,
        req,
        provider=last_ctx.get("provider"),
        key=last_ctx.get("key"),
        node=last_ctx.get("node"),
        upstream_style=last_ctx.get("upstream_style"),
        upstream_model=last_ctx.get("upstream_model"),
        status_code=last_status,
        success=False,
        attempts=attempts,
        error=last_error,
        upstream_url=last_outcome.url if last_outcome else None,
        req_method=last_outcome.req_method if last_outcome else None,
        req_headers=last_outcome.req_headers if last_outcome else None,
        resp_headers=last_outcome.resp_headers if last_outcome else None,
        resp_body=_resp_body_repr(last_outcome) if last_outcome else None,
        debug_attempts=debug_trail,
        attempt_summaries=attempt_summaries,
        started_at=dispatch_started_at,
        finished_at=_utcnow(),
    )

    # Distinguish "the gateway itself broke" from "no upstream could serve this
    # request". When nothing was ever attempted (no key / no route / all keys
    # exhausted) the upstream is simply unavailable — flag it as such with a
    # dedicated, machine-readable error type and a message that won't be mistaken
    # for a relay/proxy failure (a bare "Bad Gateway" reason phrase often is).
    return DispatchResult(
        status_code=last_status if last_status >= 400 else 502,
        is_stream=False,
        content=_error_body(
            req.inbound_style,
            f"Upstream Failed — {last_error}",
            "upstream_unavailable",
        ),
        model=req.model,
        attempts=attempts,
        error="upstream_unavailable",
    )


async def _resolve_token(
    session: Any,
    adapter: BaseProvider,
    key: ApiKey,
    secret_key: str,
    *,
    force_refresh: bool = False,
) -> str:
    return await adapter.resolve_credential(
        session,
        key,
        secret_key,
        force_refresh=force_refresh,
    )


def _prepare_body(
    req: DispatchRequest,
    adapter: BaseProvider,
    upstream_style: ApiStyle,
    upstream_model: str,
    plaintext: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    body = _translate_request(req.inbound_style, upstream_style, req.payload)
    body = dict(body)
    if upstream_style is ApiStyle.OPENAI:
        body = transform.openai_roles_to_system(body)
    body["model"] = upstream_model
    if req.stream:
        body["stream"] = True
        if upstream_style is ApiStyle.OPENAI:
            body.setdefault("stream_options", {"include_usage": True})
    else:
        body.pop("stream", None)
    return adapter.build_request(plaintext, body, req.passthrough_headers or None)


# --------------------------------------------------------------------------- #
# Single HTTP attempt
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Attempt:
    network_error: bool = False
    error: str | None = None
    is_pool_timeout: bool = False  # PoolTimeout: capacity issue, do NOT blame proxy
    # Whether this failure should count against the proxy. Capacity (PoolTimeout)
    # and total-response-timeout issues are NOT proxy faults and never penalise
    # the proxy; everything else does.
    blame_proxy: bool = True
    # Monotonic clock timestamp when the upstream request was initiated — the
    # reference point for TTFT (time to first token) and the stream timeout.
    start_mono: float | None = None
    # True when a streamed 200 response ended before producing any real content
    # — the "200 OK + 0 tokens" degenerate case. The dispatcher retries instead
    # of delivering an empty stream.
    degenerate_empty: bool = False
    status_code: int = 0
    body_bytes: bytes | None = None
    body_json: Any = None
    body_text: str | None = None  # decoded fallback when the body is not JSON
    # kept open only for a successful stream (possibly the spooled wrapper).
    response: httpx.Response | _SpooledResponse | None = None
    resp_headers: dict[str, str] | None = None
    # Outbound request metadata (captured for the debug trail; headers redacted).
    req_method: str | None = None
    url: str | None = None
    proxy_url: str | None = None
    local_address: str | None = None
    req_headers: dict[str, str] | None = None
    req_body: dict[str, Any] | None = None
    duration_ms: float | None = None


async def _attempt(
    *,
    pool: Any,
    adapter: BaseProvider,
    route: Route,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    stream: bool,
    connect_timeout: float,
    read_timeout: float,
    total_timeout: float | None = None,
    spool_first_content: bool = False,
) -> _Attempt:
    # Outbound request metadata, shared by every return path so the debug trail
    # always knows exactly what was sent where. Auth headers are masked here.
    redacted = redact_headers(headers)
    req_meta: dict[str, Any] = {
        "req_method": "POST",
        "url": url,
        "proxy_url": route.proxy_url,
        "local_address": route.local_address,
        "req_headers": redacted,
        "req_body": body,
    }
    # Verbose outbound tracing (debug mode only — gated by the log level so it
    # costs nothing when disabled). The auth header is masked by redact_headers.
    log.debug(
        "outbound_request",
        provider_type=adapter.type,
        method="POST",
        url=url,
        stream=stream,
        proxy=route.proxy_url,
        local_address=route.local_address,
        headers=redacted,
        body=body,
    )
    started = time.monotonic()

    def _elapsed_ms() -> float:
        return round((time.monotonic() - started) * 1000, 1)

    try:
        client = await pool.get(route, connect_timeout=connect_timeout, read_timeout=read_timeout)
        if stream:
            request = client.build_request("POST", url, json=body, headers=headers)
            response = await client.send(request, stream=True)
            if response.status_code >= 300:
                raw = await response.aread()
                await response.aclose()
                resp_headers = dict(response.headers)
                log.debug(
                    "upstream_response",
                    status_code=response.status_code,
                    stream=True,
                    headers=redact_headers(response.headers),
                    body=_try_json(raw),
                )
                return _Attempt(
                    status_code=response.status_code,
                    body_bytes=raw,
                    body_json=_try_json(raw),
                    body_text=_body_text(raw),
                    resp_headers=resp_headers,
                    duration_ms=_elapsed_ms(),
                    **req_meta,
                )
            log.debug(
                "upstream_response",
                status_code=response.status_code,
                stream=True,
                headers=redact_headers(response.headers),
            )
            resp_status = response.status_code
            resp_headers = dict(response.headers)
            # Degenerate-detection for the "200 OK + 0 tokens" retry feature:
            # spool until the first real content token (or the stream ends / a
            # short grace period passes). A stream that ends with no content is
            # degenerate — retried by the caller instead of delivered empty.
            if spool_first_content:
                try:
                    spooled, degenerate = await _spool_first_content(response, adapter.style)
                except Exception:
                    # Upstream faulted while spooling — close and let the caller
                    # treat it as a network error (retry).
                    await response.aclose()
                    raise
                if degenerate:
                    return _Attempt(
                        status_code=resp_status,
                        degenerate_empty=True,
                        error="upstream stream ended with no content (200 OK, 0 tokens)",
                        resp_headers=resp_headers,
                        duration_ms=_elapsed_ms(),
                        start_mono=started,
                        **req_meta,
                    )
                response = spooled
            return _Attempt(
                status_code=resp_status,
                response=response,
                resp_headers=resp_headers,
                duration_ms=_elapsed_ms(),
                start_mono=started,
                **req_meta,
            )

        if total_timeout and total_timeout > 0:
            response = await asyncio.wait_for(
                client.post(url, json=body, headers=headers), timeout=total_timeout
            )
        else:
            response = await client.post(url, json=body, headers=headers)
        raw = response.content
        log.debug(
            "upstream_response",
            status_code=response.status_code,
            stream=False,
            headers=redact_headers(response.headers),
            body=_try_json(raw),
        )
        return _Attempt(
            status_code=response.status_code,
            body_bytes=raw,
            body_json=_try_json(raw),
            body_text=_body_text(raw),
            resp_headers=dict(response.headers),
            duration_ms=_elapsed_ms(),
            **req_meta,
        )
    except _POOL_TIMEOUT_ERRORS as exc:
        pool_ref = get_pool()
        pool_info = f"pool clients={len(pool_ref._clients)}"
        detail = (
            f"PoolTimeout on {url!r} via proxy={route.proxy_url!r} "
            f"({pool_info}). The connection pool is saturated under high concurrency. "
            f"Increase max_connections in network.py or reduce concurrency. "
            f"Proxy is NOT penalised for this. Original: {exc}"
        )
        log.warning(
            "outbound_pool_timeout",
            url=url,
            proxy=route.proxy_url,
            pool_info=pool_info,
            error=str(exc),
        )
        return _Attempt(
            network_error=True,
            error=detail,
            is_pool_timeout=True,
            blame_proxy=False,
            duration_ms=_elapsed_ms(),
            **req_meta,
        )
    except TimeoutError as exc:
        detail = (
            f"Response timeout after {int(total_timeout or 0)}s on {url!r} "
            f"via proxy={route.proxy_url!r}. The upstream did not complete in time. "
            f"Proxy is NOT penalised for this. Original: {exc}"
        )
        log.warning(
            "outbound_response_timeout",
            url=url,
            proxy=route.proxy_url,
            timeout=total_timeout,
            error=str(exc),
        )
        return _Attempt(
            network_error=True,
            error=detail,
            blame_proxy=False,
            duration_ms=_elapsed_ms(),
            **req_meta,
        )
    except _NETWORK_ERRORS as exc:
        log.debug("outbound_network_error", url=url, error=f"{type(exc).__name__}: {exc}")
        return _Attempt(
            network_error=True,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=_elapsed_ms(),
            **req_meta,
        )
    except httpx.HTTPError as exc:  # any other httpx error -> treat as network
        log.debug("outbound_network_error", url=url, error=f"{type(exc).__name__}: {exc}")
        return _Attempt(
            network_error=True,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=_elapsed_ms(),
            **req_meta,
        )


# How long we wait for the first real content token of a streamed response
# before committing to forward it live. A degenerate empty 200 from a flaky
# upstream returns immediately, so this stays short; a slow-but-real generation
# merely gets forwarded a moment later (no data is lost).
_SPOOL_FIRST_CONTENT_SECONDS = 5.0


class _SpooledResponse:
    """Wraps a streaming httpx response that was partially consumed while
    checking for degenerate "200 OK + 0 tokens" replies.

    A background reader owns the httpx stream and pumps chunks into ``queue``;
    ``aiter_bytes`` first yields the buffered ``prefix``, then drains the queue
    live. This lets the dispatcher decide up front whether to retry (degenerate)
    without ever double-iterating the httpx stream.
    """

    def __init__(
        self,
        response: httpx.Response,
        prefix: bytes,
        queue: asyncio.Queue[bytes | BaseException | None],
    ) -> None:
        self._response = response
        self._prefix = prefix
        self._queue = queue
        self._reader: asyncio.Task | None = None

    def attach_reader(self, task: asyncio.Task) -> None:
        self._reader = task

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        if self._prefix:
            yield self._prefix
        while True:
            item = await self._queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item

    async def aclose(self) -> None:
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        await self._response.aclose()


async def _spool_first_content(
    response: httpx.Response,
    style: ApiStyle,
    spool_timeout: float = _SPOOL_FIRST_CONTENT_SECONDS,
) -> tuple[_SpooledResponse, bool]:
    """Read the start of a streamed upstream response to detect a degenerate
    "200 OK + 0 tokens" reply.

    Returns ``(spooled, degenerate)``: ``spooled`` is a resumable wrapper for the
    client (always returned; when degenerate the caller should not use it),
    ``degenerate`` is True when the stream ended before producing any content —
    the dispatcher retries instead of delivering an empty reply. An upstream
    error mid-spool is re-raised so the caller can treat it as a network fault.
    """
    queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()

    async def _reader() -> None:
        try:
            async for chunk in response.aiter_bytes():
                await queue.put(chunk)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # surface the fault to the consumer
            await queue.put(exc)
            return
        await queue.put(None)

    reader = asyncio.create_task(_reader())
    prefix = bytearray()
    deadline = time.monotonic() + spool_timeout
    ended = False
    while time.monotonic() < deadline:
        try:
            remaining = max(0.0, deadline - time.monotonic())
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
        except TimeoutError:
            break
        if item is None:
            ended = True
            break
        if isinstance(item, BaseException):
            raise item
        prefix += item
        if _sse_has_content(bytes(prefix), style):
            break
    spooled = _SpooledResponse(response, bytes(prefix), queue)
    spooled.attach_reader(reader)
    degenerate = ended and not _sse_has_content(bytes(prefix), style)
    if degenerate:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        await response.aclose()
    return spooled, degenerate


def _sse_has_content(buffer: bytes, style: ApiStyle) -> bool:
    """Whether a (possibly partial) SSE buffer carries a real content token.

    Content-bearing frames differ per dialect (Chat Completions ``delta.content``,
    Anthropic ``content_block_delta.text``, Responses ``output_text_delta``).
    Control frames (``[DONE]``, metadata-only, empty deltas) are ignored. As a
    fallback, a buffer with no SSE frames at all that still holds non-whitespace
    bytes is treated as content (plain-text streaming upstreams).
    """
    text = buffer.decode("utf-8", errors="ignore").replace("\r\n", "\n")
    saw_data = False
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if not line.startswith("data:"):
                continue
            saw_data = True
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if _sse_frame_has_content(obj, style):
                return True
    if not saw_data:
        return bool(text.strip())
    return False


def _sse_frame_has_content(obj: Any, style: ApiStyle) -> bool:
    if not isinstance(obj, dict):
        return False
    if style is ApiStyle.OPENAI:
        choices = obj.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") or choice.get("message")
                if isinstance(delta, dict):
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        return True
                    # tool calls carry content too
                    if delta.get("tool_calls"):
                        return True
        return False
    if style is ApiStyle.OPENAI_RESPONSES:
        if obj.get("type") == "response.output_text_delta":
            delta = obj.get("delta")
            if isinstance(delta, str) and delta:
                return True
        return False
    # Anthropic
    if obj.get("type") == "content_block_delta":
        delta = obj.get("delta")
        if isinstance(delta, dict):
            text = delta.get("text")
            if isinstance(text, str) and text:
                return True
        return False
    if obj.get("type") == "content_block_start":
        block = obj.get("content_block")
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return True
    return False


def _try_json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# Cap a captured non-JSON body so a stray HTML error page / huge payload can't
# bloat the log row. Generous enough to keep a useful upstream error message.
_MAX_BODY_TEXT = 20_000


def _body_text(raw: bytes | None) -> str | None:
    """Decoded text form of a body that isn't JSON (e.g. an HTML 5xx page)."""
    if not raw:
        return None
    if _try_json(raw) is not None:
        return None
    text = raw.decode("utf-8", errors="replace")
    if len(text) > _MAX_BODY_TEXT:
        return text[:_MAX_BODY_TEXT] + f"… [truncated {len(text) - _MAX_BODY_TEXT} chars]"
    return text


def _resp_body_repr(outcome: _Attempt) -> Any:
    """Best representation of a response body for logging: JSON if it parsed,
    else the decoded text fallback (or ``None`` when the body was empty)."""
    if outcome.body_json is not None:
        return outcome.body_json
    return outcome.body_text


def _trail_entry(
    *,
    attempt: int,
    provider: Provider,
    key: ApiKey,
    adapter: BaseProvider,
    upstream_model: str,
    outcome: _Attempt,
) -> dict[str, Any]:
    """One row of the per-attempt debug trail (redaction already applied)."""
    if outcome.network_error:
        error_class = "network_error"
    else:
        error_class = adapter.classify(outcome.status_code, outcome.body_json).value
    return {
        "attempt": attempt,
        "provider": provider.name,
        "provider_id": provider.id,
        "key_id": key.id,
        "key_preview": key.key_preview or None,
        "pool": key.pool or "",
        "upstream_model": upstream_model,
        "method": outcome.req_method,
        "url": outcome.url,
        "proxy_url": outcome.proxy_url,
        "local_address": outcome.local_address,
        "req_headers": outcome.req_headers,
        "req_body": outcome.req_body,
        "status_code": outcome.status_code or None,
        "error_class": error_class,
        "network_error": outcome.network_error,
        "error": outcome.error,
        "resp_headers": outcome.resp_headers,
        "resp_body": _resp_body_repr(outcome),
        "duration_ms": outcome.duration_ms,
    }


def _attempt_summary(
    *,
    attempt: int,
    provider: Provider,
    key: ApiKey,
    adapter: BaseProvider,
    upstream_model: str,
    outcome: _Attempt,
) -> dict[str, Any]:
    """A lightweight, always-recorded summary of one failover attempt.

    Unlike the debug trail, this is stored for every request (not debug-gated) so
    the detail modal can show each attempt's outcome: failed attempts carry their
    response/error, successful ones a single row. Full req/resp headers/bodies are
    omitted — only the response body of a *failed* attempt is kept for diagnosis.
    """
    if outcome.network_error:
        error_class = "network_error"
        ok = False
    else:
        error_class = adapter.classify(outcome.status_code, outcome.body_json).value
        ok = error_class == ErrorClass.OK.value
    return {
        "attempt": attempt,
        "provider": provider.name,
        "provider_id": provider.id,
        "key_id": key.id,
        "key_preview": key.key_preview or None,
        "pool": key.pool or "",
        "upstream_model": upstream_model,
        "url": outcome.url,
        "proxy_url": outcome.proxy_url,
        "status_code": outcome.status_code or None,
        "error_class": error_class,
        "network_error": outcome.network_error,
        "error": outcome.error,
        # Keep the upstream error body so a failed attempt is diagnosable; omit
        # the body on success (it's large and unneeded for a summary).
        "resp_body": _resp_body_repr(outcome) if not ok else None,
        "duration_ms": outcome.duration_ms,
    }


# --------------------------------------------------------------------------- #
# Success finalisation (stream + non-stream)
# --------------------------------------------------------------------------- #


async def _finalise_success(
    *,
    session: Any,
    req: DispatchRequest,
    provider: Provider,
    adapter: BaseProvider,
    key: ApiKey,
    node: Node | None,
    outcome: _Attempt,
    upstream_model: str,
    attempts: int,
    debug_attempts: list[dict[str, Any]] | None = None,
    attempt_summaries: list[dict[str, Any]] | None = None,
    started_at: dt.datetime | None = None,
    response_timeout: float = 0,
) -> DispatchResult:
    upstream_style = adapter.style

    if req.stream and outcome.response is not None:
        # Log the success now (tokens filled in when the stream ends).
        debug = req.debug_enabled
        log_row = RequestLog(
            token_id=req.token_id,
            user_sub=req.user_sub,
            session_id=_session_key(req),
            provider_id=provider.id,
            provider_name=provider.name,
            key_id=key.id,
            proxy_id=node.id if node else None,
            model=req.model,
            upstream_model=upstream_model,
            inbound_style=req.inbound_style.value,
            upstream_style=upstream_style.value,
            status_code=outcome.status_code,
            success=True,
            stream=True,
            attempts=attempts,
            user_agent=req.user_agent,
            client_type=req.client_type,
            is_opencode=req.is_opencode,
            debug=debug,
            req_method=outcome.req_method,
            req_body=req.payload if debug else None,
            req_headers=outcome.req_headers if debug else None,
            resp_headers=outcome.resp_headers if debug else None,
            debug_attempts=debug_attempts if debug else None,
            attempts_summary=attempt_summaries,
            upstream_url=outcome.url if debug else None,
            proxy_url=node.url if node and debug else None,
            client_ip=req.client_ip,
            started_at=started_at or _utcnow(),
            req_status="pending",
        )
        session.add(log_row)
        await session.flush()
        log_id = log_row.id
        token_id = req.token_id

        stream_iter = _build_stream(
            response=outcome.response,
            inbound=req.inbound_style,
            upstream=upstream_style,
            model=req.model,
            log_id=log_id,
            token_id=token_id,
            response_timeout=response_timeout,
            start_mono=outcome.start_mono,
        )
        return DispatchResult(
            status_code=200,
            is_stream=True,
            media_type="text/event-stream",
            stream=stream_iter,
            provider_name=provider.name,
            upstream_style=upstream_style.value,
            model=req.model,
            attempts=attempts,
        )

    # Non-streaming success.
    upstream_json = outcome.body_json
    usage = _extract_usage(upstream_json, upstream_style)
    # Translation expects a JSON object; a non-object JSON body (``[]``, ``42``,
    # ``"ok"``) from a misbehaving upstream must be passed through verbatim rather
    # than crashing the translator (which would 500 after the upstream was billed).
    if isinstance(upstream_json, dict):
        translated = _translate_response(
            req.inbound_style, upstream_style, upstream_json, req.model
        )
        content = json.dumps(translated).encode()
    else:
        content = outcome.body_bytes or b"{}"

    # ``key.total_requests`` and the rate-limit reward are already applied by the
    # caller's OK branch before we get here — don't double-count them.
    await _log_request(
        session,
        req,
        provider=provider,
        key=key,
        node=node,
        upstream_style=upstream_style,
        upstream_model=upstream_model,
        status_code=outcome.status_code,
        success=True,
        attempts=attempts,
        error=None,
        usage=usage,
        upstream_url=outcome.url,
        req_method=outcome.req_method,
        req_headers=outcome.req_headers,
        resp_headers=outcome.resp_headers,
        resp_body=_resp_body_repr(outcome),
        debug_attempts=debug_attempts,
        attempt_summaries=attempt_summaries,
        started_at=started_at,
        finished_at=_utcnow(),
    )
    await _bump_token_usage(session, req.token_id, usage["total_tokens"])

    return DispatchResult(
        status_code=200,
        is_stream=False,
        content=content,
        provider_name=provider.name,
        upstream_style=upstream_style.value,
        model=req.model,
        attempts=attempts,
    )


async def _stream_cleanup(
    response: httpx.Response | _SpooledResponse,
    log_id: int,
    token_id: int | None,
    usage: dict[str, int],
    *,
    req_status: str,
    first_token_ms: float | None,
    finished_at: dt.datetime,
    error: str | None = None,
) -> None:
    """Close the upstream response and persist captured usage — shielded caller."""
    await response.aclose()
    await _persist_stream_usage(
        log_id,
        token_id,
        usage,
        req_status=req_status,
        first_token_ms=first_token_ms,
        finished_at=finished_at,
        error=error,
    )


async def _build_stream(
    *,
    response: httpx.Response | _SpooledResponse,
    inbound: ApiStyle,
    upstream: ApiStyle,
    model: str,
    log_id: int,
    token_id: int | None,
    response_timeout: float = 0,
    start_mono: float | None = None,
) -> AsyncIterator[bytes]:
    """Yield translated SSE bytes, then persist token usage on completion.

    TTFT (``first_token_ms``) is measured from the moment the successful
    upstream request was initiated (``start_mono``, threaded through the
    attempt) to the first *content-bearing* SSE frame — not the first raw byte,
    which only reflects the upstream's connection/header latency. Control frames
    (``message_start``, ``content_block_start``, ``ping``, ``[DONE]``, empty
    role deltas) are skipped by ``_sse_frame_has_content``.

    When ``response_timeout`` > 0 the stream is force-cut once it has run past
    that wall-clock deadline (the connection is closed and the log row marked
    ``terminated``).
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if start_mono is None:
        start_mono = time.monotonic()
    # A mutable holder so _capture_usage can stamp the first-token moment.
    first_token: dict[str, float | None] = {"ms": None}

    async def _raw() -> AsyncIterator[bytes]:
        async for chunk in response.aiter_bytes():
            yield chunk

    translated = _translate_stream(
        inbound,
        upstream,
        _capture_usage(
            _raw(), usage, upstream_style=upstream, first_token=first_token, start_mono=start_mono
        ),
        model,
    )
    req_status = "completed"
    stream_error: str | None = None
    it = translated.__aiter__()
    try:
        while True:
            remaining = 0.0
            if response_timeout and response_timeout > 0:
                remaining = response_timeout - (time.monotonic() - start_mono)
                if remaining <= 0:
                    req_status = "terminated"
                    stream_error = (
                        f"response timeout after {int(response_timeout)}s — connection cut"
                    )
                    break
            try:
                if remaining > 0:
                    piece = await asyncio.wait_for(it.__anext__(), timeout=remaining)
                else:
                    piece = await it.__anext__()
            except StopAsyncIteration:
                break
            except TimeoutError:
                req_status = "terminated"
                stream_error = f"response timeout after {int(response_timeout)}s — connection cut"
                break
            yield piece
    except asyncio.CancelledError:
        req_status = "cancelled"
        raise
    except GeneratorExit:
        # Starlette abandons the iterator on client disconnect — record it as
        # cancelled rather than a clean completion.
        req_status = "cancelled"
        raise
    except httpx.TransportError as exc:
        # The upstream closed the connection mid-stream (incomplete chunked
        # read, peer reset, …). Bytes are already flowing to the client, so a
        # traceback would only flood the logs: record a concise error, persist
        # usage in the finally block, and let the stream end cleanly.
        req_status = "error"
        stream_error = f"upstream connection closed: {type(exc).__name__}: {exc}"
        log.warning("stream_upstream_closed", log_id=log_id, error=stream_error)
    except Exception:
        req_status = "error"
        raise
    finally:
        finished_at = _utcnow()
        # Free the translation generator chain (it may still be buffering chunks
        # after a timeout/terminated break) before closing the upstream response.
        with contextlib.suppress(asyncio.CancelledError, GeneratorExit, Exception):
            await cast(AsyncGenerator[bytes], it).aclose()
        # Shield the upstream-response close + usage persistence so they complete
        # even when the client disconnects mid-stream (CancelledError). Without
        # the shield, the cancellation propagates into these awaits and the
        # upstream connection leaks / usage is lost.
        try:
            await asyncio.shield(
                _stream_cleanup(
                    response,
                    log_id,
                    token_id,
                    usage,
                    req_status=req_status,
                    first_token_ms=first_token["ms"],
                    finished_at=finished_at,
                    error=stream_error,
                )
            )
        except asyncio.CancelledError:
            log.debug("stream_cancelled", log_id=log_id)


async def _capture_usage(
    raw: AsyncIterator[bytes],
    usage: dict[str, int],
    *,
    upstream_style: ApiStyle,
    first_token: dict[str, float | None],
    start_mono: float,
) -> AsyncIterator[bytes]:
    """Tee the raw upstream stream to sniff usage without altering bytes.

    Also stamps the TTFT: the elapsed time from ``start_mono`` to the first
    SSE block carrying a real content token. Only the first occurrence counts;
    ``first_token["ms"]`` stays ``None`` for a stream that never produced
    content (e.g. a pure error/control stream).
    """
    buffer = ""
    async for chunk in raw:
        # Normalise CRLF so usage blocks split on "\n\n" for both line styles.
        buffer += chunk.decode("utf-8", errors="ignore").replace("\r\n", "\n")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            _sniff_usage(block, usage)
            if first_token["ms"] is None and _sse_has_content(
                block.encode("utf-8"), upstream_style
            ):
                first_token["ms"] = (time.monotonic() - start_mono) * 1000.0
        yield chunk
    if buffer:
        _sniff_usage(buffer, usage)
        if first_token["ms"] is None and _sse_has_content(buffer.encode("utf-8"), upstream_style):
            first_token["ms"] = (time.monotonic() - start_mono) * 1000.0


def _sniff_usage(block: str, usage: dict[str, int]) -> None:
    for line in block.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        # OpenAI style
        if isinstance(obj, dict) and obj.get("usage"):
            u = obj["usage"]
            usage["prompt_tokens"] = u.get("prompt_tokens", usage["prompt_tokens"])
            usage["completion_tokens"] = u.get("completion_tokens", usage["completion_tokens"])
        # Anthropic style
        if isinstance(obj, dict):
            if obj.get("type") == "message_start":
                u = obj.get("message", {}).get("usage", {})
                usage["prompt_tokens"] = u.get("input_tokens", usage["prompt_tokens"])
            if obj.get("type") == "message_delta" and obj.get("usage"):
                usage["completion_tokens"] = obj["usage"].get(
                    "output_tokens", usage["completion_tokens"]
                )
            # OpenAI Responses style — usage rides the terminal completed event.
            if obj.get("type") in ("response.completed", "response.incomplete"):
                u = (obj.get("response") or {}).get("usage") or {}
                usage["prompt_tokens"] = u.get("input_tokens", usage["prompt_tokens"])
                usage["completion_tokens"] = u.get("output_tokens", usage["completion_tokens"])
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]


# How hard we try to persist end-of-stream usage before giving up. The stream
# has already been delivered to the client by this point, so a transient DB blip
# must not lose the usage/quota accounting silently.
_STREAM_USAGE_PERSIST_ATTEMPTS = 3
_STREAM_USAGE_RETRY_BASE_DELAY = 0.5  # seconds; exponential, capped at 5s


async def _persist_stream_usage(
    log_id: int,
    token_id: int | None,
    usage: dict[str, int],
    *,
    req_status: str = "completed",
    first_token_ms: float | None = None,
    finished_at: dt.datetime | None = None,
    error: str | None = None,
) -> None:
    """Write final stream token usage back to the log row + token quota.

    Retries a few times on transient database errors — the stream is already
    delivered, so this write happening late is fine but losing it is not. If
    every attempt fails, log at ``error`` with the full usage payload so the loss
    is at least traceable (and recoverable) instead of silently swallowed.
    """
    db = get_database()
    last_exc: Exception | None = None
    for attempt in range(1, _STREAM_USAGE_PERSIST_ATTEMPTS + 1):
        try:
            async with db.session() as session:
                row = await session.get(RequestLog, log_id)
                if row is not None:
                    row.prompt_tokens = usage["prompt_tokens"]
                    row.completion_tokens = usage["completion_tokens"]
                    row.total_tokens = usage["total_tokens"]
                    row.req_status = req_status
                    if error is not None:
                        row.error = error
                    if first_token_ms is not None:
                        row.first_token_ms = first_token_ms
                    row.finished_at = finished_at or _utcnow()
                    # Fold this (now token-complete) streamed request into the
                    # heatmap rollups exactly once, at the point tokens are known.
                    await usage_rollup.record_usage(
                        session,
                        user_sub=row.user_sub,
                        session_key=row.session_id,
                        tokens=usage["total_tokens"],
                        ts=row.ts,
                    )
                await _bump_token_usage(session, token_id, usage["total_tokens"])
            return
        except Exception as exc:
            last_exc = exc
            log.warning(
                "stream_usage_persist_retry",
                attempt=attempt,
                max_attempts=_STREAM_USAGE_PERSIST_ATTEMPTS,
                error=str(exc),
                log_id=log_id,
            )
            if attempt < _STREAM_USAGE_PERSIST_ATTEMPTS:
                delay = min(_STREAM_USAGE_RETRY_BASE_DELAY * 2 ** (attempt - 1), 5.0)
                await asyncio.sleep(delay)
    # Exhausted every retry — surface the loss with the numbers needed to reconcile.
    log.error(
        "stream_usage_persist_failed",
        error=str(last_exc),
        log_id=log_id,
        token_id=token_id,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
    )


def _extract_usage(body: Any, upstream: ApiStyle) -> dict[str, int]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if not isinstance(body, dict):
        return usage
    if upstream in (ApiStyle.ANTHROPIC, ApiStyle.OPENAI_RESPONSES):
        u = body.get("usage", {})
        usage["prompt_tokens"] = u.get("input_tokens", 0)
        usage["completion_tokens"] = u.get("output_tokens", 0)
    else:
        u = body.get("usage", {})
        usage["prompt_tokens"] = u.get("prompt_tokens", 0)
        usage["completion_tokens"] = u.get("completion_tokens", 0)
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def _passthrough_error(
    req: DispatchRequest, outcome: _Attempt, upstream_style: ApiStyle
) -> DispatchResult:
    if req.inbound_style == upstream_style and outcome.body_bytes:
        content = outcome.body_bytes
    elif outcome.body_json is not None:
        msg = _error_message(outcome.body_json)
        content = _error_body(req.inbound_style, msg, "invalid_request_error")
    else:
        content = _error_body(req.inbound_style, f"Upstream returned {outcome.status_code}")
    return DispatchResult(
        status_code=outcome.status_code,
        is_stream=False,
        content=content,
        upstream_style=upstream_style.value,
        model=req.model,
    )


def _error_message(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", "request error"))
        if isinstance(err, str):
            return err
    return "request error"


# --------------------------------------------------------------------------- #
# Logging helpers
# --------------------------------------------------------------------------- #


async def _log_request(
    session: Any,
    req: DispatchRequest,
    *,
    provider: Provider | None,
    key: ApiKey | None,
    node: Node | None,
    upstream_style: ApiStyle | None,
    status_code: int,
    success: bool,
    attempts: int,
    error: str | None,
    usage: dict[str, int] | None = None,
    upstream_url: str | None = None,
    upstream_model: str | None = None,
    req_method: str | None = None,
    req_headers: dict[str, Any] | None = None,
    resp_headers: dict[str, Any] | None = None,
    resp_body: Any = None,
    debug_attempts: list[dict[str, Any]] | None = None,
    attempt_summaries: list[dict[str, Any]] | None = None,
    started_at: dt.datetime | None = None,
    finished_at: dt.datetime | None = None,
    first_token_ms: float | None = None,
    req_status: str | None = None,
) -> None:
    usage = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    debug = req.debug_enabled
    # Force-capture the upstream response (headers + body only) on any error —
    # even for non-debug tokens — so an upstream 4xx/5xx is always diagnosable.
    # The request headers/body and the per-attempt trail are NOT captured in this
    # forced case (only full debug tokens get those). This capture is treated as
    # debug info: it is owner-only in the UI and pruned by the same
    # ``debug_log_retention_days`` window, so the row is flagged ``debug``.
    error_capture = (
        not debug
        and not success
        and status_code is not None
        and status_code >= 400
        and (resp_headers is not None or resp_body is not None)
    )
    store_resp = debug or error_capture
    session_key = _session_key(req)
    now = _utcnow()
    session.add(
        RequestLog(
            token_id=req.token_id,
            user_sub=req.user_sub,
            session_id=session_key,
            provider_id=provider.id if provider else None,
            provider_name=provider.name if provider else None,
            key_id=key.id if key else None,
            proxy_id=node.id if node else None,
            model=req.model,
            upstream_model=upstream_model,
            inbound_style=req.inbound_style.value,
            upstream_style=upstream_style.value if upstream_style else None,
            status_code=status_code,
            success=success,
            stream=req.stream,
            attempts=attempts,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            error=error,
            user_agent=req.user_agent,
            client_type=req.client_type,
            is_opencode=req.is_opencode,
            debug=debug or error_capture,
            req_method=req_method,
            req_headers=req_headers if debug else None,
            req_body=req.payload if debug else None,
            resp_headers=resp_headers if store_resp else None,
            resp_body=resp_body if store_resp else None,
            debug_attempts=debug_attempts if debug else None,
            attempts_summary=attempt_summaries,
            upstream_url=upstream_url,
            proxy_url=node.url if node and debug else None,
            client_ip=req.client_ip,
            started_at=started_at or now,
            finished_at=finished_at or now,
            first_token_ms=first_token_ms,
            req_status=req_status or ("completed" if success else "error"),
        )
    )
    # Fold every non-streamed request (success or failure) into the heatmap
    # rollups. Streamed successes are recorded separately in _persist_stream_usage
    # once their final token count is known, so they are not double-counted here.
    await usage_rollup.record_usage(
        session,
        user_sub=req.user_sub,
        session_key=session_key,
        tokens=usage["total_tokens"],
    )


async def _bump_token_usage(session: Any, token_id: int | None, tokens: int) -> None:
    if token_id is None:
        return
    from voidswitch.models.db import VoidToken

    row = await session.get(VoidToken, token_id)
    if row is not None:
        row.total_requests += 1
        row.total_tokens += max(tokens, 0)
        row.last_used_at = _utcnow()


# --------------------------------------------------------------------------- #
# Pending-log reconciliation
# --------------------------------------------------------------------------- #


async def reconcile_pending_request_logs() -> int:
    """Mark orphaned ``pending`` log rows as ``terminated``.

    A streamed request whose row is still ``pending`` long after ``started_at``
    means its end-of-stream persistence never ran (e.g. the worker was killed
    mid-stream, or the stream was abandoned without being closed). There is no
    legitimate request that outlives the configured ``response_timeout_seconds``
    (0 = disabled), so anything still pending past that is force-marked
    ``terminated``. Returns the number of rows reconciled.
    """
    timeout = settings_store.get_int("response_timeout_seconds", 3600)
    if timeout <= 0:
        return 0
    from sqlalchemy import update

    db = get_database()
    cutoff = _utcnow() - dt.timedelta(seconds=timeout)
    async with db.session() as session:
        result = await session.execute(
            update(RequestLog)
            .where(RequestLog.req_status == "pending", RequestLog.started_at < cutoff)
            .values(
                req_status="terminated",
                error="connection cut — response timeout exceeded while stream was abandoned",
                finished_at=_utcnow(),
            )
        )
        await session.commit()
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        log.warning("pending_logs_reconciled", count=count, timeout=timeout)
    return count
