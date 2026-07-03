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
import datetime as dt
import hashlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from voidswitch.constants import ApiStyle, KeyStatus, ProxyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger, redact_headers
from voidswitch.core.security import decrypt_secret
from voidswitch.models.db import ApiKey, Provider, Proxy, RequestLog
from voidswitch.services import oauth_tokens, settings_store, transform
from voidswitch.services.network import Route, get_pool
from voidswitch.services.providers.base import BaseProvider, ErrorClass
from voidswitch.services.providers.registry import get_adapter
from voidswitch.services.selector import (
    active_proxies,
    resolve_model,
    routes_for_provider,
    select_keys,
    select_providers,
    static_routes,
)

log = get_logger("dispatcher")

_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stringify(value: Any) -> str:
    """Stable string form of a payload fragment for session hashing."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


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
        return f"t{req.token_id}:sid:{req.session_id}"
    payload = req.payload or {}
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        uid = meta.get("user_id")
        if isinstance(uid, str) and uid:
            return f"t{req.token_id}:u:{uid}"
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


def _penalize_proxy(proxy: Proxy | None, reason: str, threshold: int) -> None:
    if proxy is None:
        return
    proxy.failed_count += 1
    proxy.last_checked_at = _utcnow()
    if proxy.failed_count >= threshold:
        proxy.status = ProxyStatus.DISABLED.value
        proxy.disabled_reason = reason


def _reward_proxy(proxy: Proxy | None) -> None:
    if proxy is None:
        return
    if proxy.failed_count:
        proxy.failed_count = 0
    proxy.last_used_at = _utcnow()


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


async def dispatch(req: DispatchRequest) -> DispatchResult:
    db = get_database()
    settings = get_settings()
    max_retries = max(1, settings_store.get_int("max_retries", 6))
    proxy_threshold = max(1, settings_store.get_int("max_proxy_failures", 3))
    connect_timeout = float(settings_store.get_int("connect_timeout_seconds", 15))
    request_timeout = float(settings_store.get_int("request_timeout_seconds", 300))
    stream_idle = float(settings_store.get_int("stream_idle_timeout_seconds", 120))
    rate_limit_recovery = settings_store.get_int("rate_limit_recovery_seconds", 180)
    rate_limit_max_cooldown = settings_store.get_int("rate_limit_max_cooldown_seconds", 3600)

    pool = get_pool()
    attempts = 0
    last_error = "no upstream available"
    last_status = 502
    session_key = _session_key(req)

    # Per-attempt debug trail (only populated for debug-enabled tokens) and the
    # context of the most recent attempt — so that even a total failover
    # exhaustion is attributable to the provider / key / route / upstream model it
    # last tried (instead of a bare "provider —, route anthropic→?").
    debug_trail: list[dict[str, Any]] = []
    last_ctx: dict[str, Any] = {}
    last_outcome: _Attempt | None = None

    async with db.session() as session:
        providers = await select_providers(session, req.model)
        if not providers:
            return DispatchResult(
                status_code=404,
                is_stream=False,
                content=_error_body(
                    req.inbound_style,
                    f"No enabled provider serves model '{req.model}'.",
                    "model_not_found",
                ),
                model=req.model,
            )
        # Proxy switching off (external proxy like mihomo handles egress): every
        # request goes through a single fixed route and no proxy is ever disabled.
        proxy_switching = settings_store.get_bool("proxy_switching_enabled", True)
        fixed_routes = (
            None
            if proxy_switching
            else static_routes(settings_store.get_str("static_proxy_url", ""))
        )
        proxy_pool = await active_proxies(session) if proxy_switching else []

        for provider in providers:
            # Per-provider outbound routes — honours proxy_mode (all/direct/selected),
            # unless proxy switching is disabled (then a single fixed route is used).
            routes = (
                fixed_routes
                if fixed_routes is not None
                else routes_for_provider(provider, proxy_pool)
            )
            if not routes:
                last_error = (
                    f"provider '{provider.name}': no available proxy (mode={provider.proxy_mode})"
                )
                last_status = 502
                continue
            adapter = get_adapter(provider)
            # Alias routing: pick the upstream model + key pool for this inbound model.
            upstream_model, key_pool = resolve_model(provider, req.model)
            keys = select_keys(
                provider,
                key_pool,
                rate_limit_recovery_seconds=rate_limit_recovery,
                session_key=session_key,
            )
            upstream_style = adapter.style
            timeout_override = provider.timeout_seconds or 0
            read_timeout = float(timeout_override) if timeout_override else request_timeout

            is_oauth = provider.type == "claude-code"
            secret_key = settings.server.secret_key

            for key in keys:
                if attempts >= max_retries:
                    break
                try:
                    plaintext = await _resolve_token(session, provider, key, secret_key)
                except Exception as exc:
                    _disable_key(key, KeyStatus.INVALID, f"token resolve failed: {exc}")
                    last_error = "token resolve failed"
                    last_status = 401
                    await session.flush()
                    continue  # next key
                body = _prepare_body(req, adapter, upstream_style, upstream_model)
                headers = adapter.headers(plaintext, req.passthrough_headers or None)

                oauth_refreshed = False
                route_attempts = 0
                route_cursor = _route_start(key.id, len(routes))
                while attempts < max_retries and route_attempts < len(routes):
                    route, proxy = routes[route_cursor % len(routes)]
                    route_cursor += 1
                    route_attempts += 1
                    attempts += 1
                    outcome = await _attempt(
                        pool=pool,
                        adapter=adapter,
                        route=route,
                        url=adapter.upstream_url,
                        headers=headers,
                        body=body,
                        stream=req.stream,
                        connect_timeout=connect_timeout,
                        read_timeout=stream_idle if req.stream else read_timeout,
                    )

                    # Remember this attempt for traceability + the debug trail.
                    last_outcome = outcome
                    last_ctx = {
                        "provider": provider,
                        "key": key,
                        "proxy": proxy,
                        "upstream_style": upstream_style,
                        "upstream_model": upstream_model,
                    }
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
                        _penalize_proxy(proxy, last_error, proxy_threshold)
                        await session.flush()
                        continue  # keep key, next route

                    # We have an HTTP response.
                    _reward_proxy(proxy)
                    err_class = adapter.classify(outcome.status_code, outcome.body_json)

                    if err_class is ErrorClass.OK:
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
                            proxy=proxy,
                            outcome=outcome,
                            upstream_model=upstream_model,
                            attempts=attempts,
                            debug_attempts=debug_trail,
                        )

                    if err_class in (ErrorClass.KEY_INVALID, ErrorClass.INSUFFICIENT_BALANCE):
                        # Claude Code OAuth: a 401 usually means the access token
                        # expired — force-refresh and retry this key once before
                        # giving up on it (mirrors the CLI's 401 behaviour).
                        if err_class is ErrorClass.KEY_INVALID and is_oauth and not oauth_refreshed:
                            oauth_refreshed = True
                            try:
                                plaintext = await _resolve_token(
                                    session, provider, key, secret_key, force_refresh=True
                                )
                                headers = adapter.headers(
                                    plaintext, req.passthrough_headers or None
                                )
                                route_attempts = 0
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
                        proxy=proxy,
                        upstream_style=upstream_style,
                        upstream_model=upstream_model,
                        status_code=outcome.status_code,
                        success=False,
                        attempts=attempts,
                        error=f"client error {outcome.status_code}",
                        upstream_url=adapter.upstream_url,
                        req_method=outcome.req_method,
                        req_headers=outcome.req_headers,
                        resp_headers=outcome.resp_headers,
                        resp_body=_resp_body_repr(outcome),
                        debug_attempts=debug_trail,
                    )
                    return _passthrough_error(req, outcome, upstream_style)

        # Exhausted everything. Attribute the failure to the last provider / key /
        # route / upstream model actually tried (when any attempt happened) and,
        # for debug tokens, attach the last upstream response + the full per-attempt
        # trail — so an "upstream 500" is diagnosable instead of a bare provider "—".
        await _log_request(
            session,
            req,
            provider=last_ctx.get("provider"),
            key=last_ctx.get("key"),
            proxy=last_ctx.get("proxy"),
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


def _route_start(seed: int, n: int) -> int:
    return seed % n if n else 0


async def _resolve_token(
    session: Any,
    provider: Provider,
    key: ApiKey,
    secret_key: str,
    *,
    force_refresh: bool = False,
) -> str:
    """Resolve the credential to send: a refreshed OAuth token for claude-code,
    or the decrypted static key for everything else."""
    if provider.type == "claude-code":
        return await oauth_tokens.resolve_access_token(
            session, key, secret_key=secret_key, force_refresh=force_refresh
        )
    return decrypt_secret(key.key_ciphertext, secret=secret_key)


def _prepare_body(
    req: DispatchRequest,
    adapter: BaseProvider,
    upstream_style: ApiStyle,
    upstream_model: str,
) -> dict:
    body = _translate_request(req.inbound_style, upstream_style, req.payload)
    body = dict(body)
    body["model"] = upstream_model
    if req.stream:
        body["stream"] = True
        if upstream_style is ApiStyle.OPENAI:
            body.setdefault("stream_options", {"include_usage": True})
    else:
        body.pop("stream", None)
    # Provider-specific final mutation (e.g. Claude Code identity injection).
    return adapter.prepare_body(body)


# --------------------------------------------------------------------------- #
# Single HTTP attempt
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Attempt:
    network_error: bool = False
    error: str | None = None
    status_code: int = 0
    body_bytes: bytes | None = None
    body_json: Any = None
    body_text: str | None = None  # decoded fallback when the body is not JSON
    response: httpx.Response | None = None  # kept open only for a successful stream
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
            return _Attempt(
                status_code=response.status_code,
                response=response,
                resp_headers=dict(response.headers),
                duration_ms=_elapsed_ms(),
                **req_meta,
            )

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
    proxy: Proxy | None,
    outcome: _Attempt,
    upstream_model: str,
    attempts: int,
    debug_attempts: list[dict[str, Any]] | None = None,
) -> DispatchResult:
    upstream_style = adapter.style

    if req.stream and outcome.response is not None:
        # Log the success now (tokens filled in when the stream ends).
        debug = req.debug_enabled
        log_row = RequestLog(
            token_id=req.token_id,
            user_sub=req.user_sub,
            provider_id=provider.id,
            provider_name=provider.name,
            key_id=key.id,
            proxy_id=proxy.id if proxy else None,
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
            upstream_url=adapter.upstream_url if debug else None,
            proxy_url=proxy.url if proxy and debug else None,
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
    if upstream_json is not None:
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
        proxy=proxy,
        upstream_style=upstream_style,
        upstream_model=upstream_model,
        status_code=outcome.status_code,
        success=True,
        attempts=attempts,
        error=None,
        usage=usage,
        upstream_url=adapter.upstream_url,
        req_method=outcome.req_method,
        req_headers=outcome.req_headers,
        resp_headers=outcome.resp_headers,
        resp_body=_resp_body_repr(outcome),
        debug_attempts=debug_attempts,
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
    response: httpx.Response, log_id: int, token_id: int | None, usage: dict[str, int]
) -> None:
    """Close the upstream response and persist captured usage — shielded caller."""
    await response.aclose()
    await _persist_stream_usage(log_id, token_id, usage)


async def _build_stream(
    *,
    response: httpx.Response,
    inbound: ApiStyle,
    upstream: ApiStyle,
    model: str,
    log_id: int,
    token_id: int | None,
) -> AsyncIterator[bytes]:
    """Yield translated SSE bytes, then persist token usage on completion."""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def _raw() -> AsyncIterator[bytes]:
        async for chunk in response.aiter_bytes():
            yield chunk

    translated = _translate_stream(inbound, upstream, _capture_usage(_raw(), usage), model)
    try:
        async for piece in translated:
            yield piece
    finally:
        # Shield the upstream-response close + usage persistence so they complete
        # even when the client disconnects mid-stream (CancelledError). Without
        # the shield, the cancellation propagates into these awaits and the
        # upstream connection leaks / usage is lost.
        try:
            await asyncio.shield(_stream_cleanup(response, log_id, token_id, usage))
        except asyncio.CancelledError:
            log.debug("stream_cancelled", log_id=log_id)


async def _capture_usage(raw: AsyncIterator[bytes], usage: dict[str, int]) -> AsyncIterator[bytes]:
    """Tee the raw upstream stream to sniff usage without altering bytes."""
    buffer = ""
    async for chunk in raw:
        buffer += chunk.decode("utf-8", errors="ignore")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            _sniff_usage(block, usage)
        yield chunk
    if buffer:
        _sniff_usage(buffer, usage)


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


async def _persist_stream_usage(log_id: int, token_id: int | None, usage: dict[str, int]) -> None:
    db = get_database()
    try:
        async with db.session() as session:
            row = await session.get(RequestLog, log_id)
            if row is not None:
                row.prompt_tokens = usage["prompt_tokens"]
                row.completion_tokens = usage["completion_tokens"]
                row.total_tokens = usage["total_tokens"]
            await _bump_token_usage(session, token_id, usage["total_tokens"])
    except Exception as exc:
        log.warning("stream_usage_persist_failed", error=str(exc), log_id=log_id)


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
    proxy: Proxy | None,
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
    session.add(
        RequestLog(
            token_id=req.token_id,
            user_sub=req.user_sub,
            provider_id=provider.id if provider else None,
            provider_name=provider.name if provider else None,
            key_id=key.id if key else None,
            proxy_id=proxy.id if proxy else None,
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
            upstream_url=upstream_url,
            proxy_url=proxy.url if proxy and debug else None,
        )
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
