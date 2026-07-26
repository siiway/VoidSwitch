"""xAI (Grok) OAuth token refresh for the official ``api.x.ai`` adapter.

Unlike :mod:`voidswitch.services.oauth_tokens` (Claude Code), this module
implements *only* the refresh half of the flow — there is no interactive login
here. It exists so an ``xai`` provider key stored as an xAI OAuth credential
bundle can be kept alive by exchanging its rotating ``refresh_token`` for a
fresh ``access_token`` against xAI's auth server.

Where the bundles come from
---------------------------
External tools (``sub2api`` in particular) convert a browser ``sso`` cookie into
an xAI OAuth ``refresh_token`` server-side and export *only* that refresh token
(no access token). :mod:`voidswitch.services.auth_import` ingests those as a
bundle ``{"refresh_token": ...}`` — possibly without ``access_token`` or
``expires_at`` — and this module mints/refreshes the access token on demand. A
plain ``xai-…`` API key (not JSON) is treated as a static token and returned
as-is.

An ``xai`` key may therefore be stored as either:

* a plain long-lived ``xai-…`` API key — used as-is, never refreshed; or
* an OAuth bundle JSON ``{"access_token"?, "refresh_token", "expires_at"?}`` —
  refreshed near expiry, when missing an access token, and on a forced 401
  retry, re-encrypting the rotated bundle back into the key.

Constants verified against the ``grok-cli`` OAuth client (public device-flow
client id) and the ``sso_convert`` reference: the refresh grant is the standard
OAuth2 ``refresh_token`` grant against ``https://auth.x.ai/oauth2/token``.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.core.security import decrypt_secret, encrypt_secret
from voidswitch.models.db import ApiKey, RequestLog
from voidswitch.services import refresh_context, settings_store
from voidswitch.services.network import Route, get_pool

log = get_logger("xai_oauth")

# Public grok-cli OAuth client (device-authorization / refresh client). This is
# not a secret — it identifies the CLI application to xAI's auth server.
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
TOKEN_HOST_MODEL = "<xai-token>"
REFRESH_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "grok-cli:access",
    "api:access",
    "conversations:read",
    "conversations:write",
)
NEAR_EXPIRY_SECONDS = 300  # refresh 5 minutes before expiry
DEFAULT_EXPIRES_IN = 21600  # xAI access tokens live ~6h when unspecified

# xAI's auth endpoint, like Claude's, is picky about datacenter IPs and default
# user-agents; send a CLI-style UA and route through the configured proxies.
OAUTH_USER_AGENT = "grok-cli/1.0.0"
_TOKEN_HEADERS = {"User-Agent": OAUTH_USER_AGENT}

_locks: dict[int, asyncio.Lock] = {}


class NotRefreshable(Exception):
    """Raised when a force-refresh is requested but the key cannot be refreshed."""


class RefreshUpstreamError(Exception):
    """Every egress route failed to reach xAI's token endpoint."""


def _lock_for(key_id: int) -> asyncio.Lock:
    lock = _locks.get(key_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key_id] = lock
    return lock


def parse_bundle(plaintext: str) -> dict[str, Any] | None:
    """Return the OAuth bundle if ``plaintext`` is one, else None (static token).

    A bundle qualifies when the decoded JSON object carries *either* an
    ``access_token`` or a ``refresh_token`` — sub2api exports refresh-only
    bundles with no access token yet, and those must still be recognised so they
    can be refreshed into a usable access token.
    """
    try:
        data = json.loads(plaintext)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and ("access_token" in data or "refresh_token" in data):
        return data
    return None


def _near_expiry(bundle: dict[str, Any]) -> bool:
    expires_at = bundle.get("expires_at")
    if not expires_at:
        return False
    try:
        return time.time() + NEAR_EXPIRY_SECONDS >= float(expires_at)
    except (TypeError, ValueError):
        return False


async def _select_routes(session: AsyncSession | None) -> list[Route]:
    """Outbound routes for OAuth calls, matching normal upstream egress settings."""
    from voidswitch.services.selector import static_routes

    if not settings_store.get_bool("proxy_switching_enabled", True):
        return [route for route, _ in static_routes(settings_store.get_str("static_proxy_url", ""))]
    if session is None:
        return [Route()]
    # Imported lazily to avoid any import cycle through the selector.
    from voidswitch.services.selector import select_routes

    return [route for route, _ in await select_routes(session)]


def _short_reason(resp: httpx.Response) -> str:
    """A concise, non-secret reason from an OAuth error response (never the raw body)."""
    with contextlib.suppress(Exception):
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("type") or "rejected")
            if isinstance(err, str):
                return str(body.get("error_description") or err)
    return "rejected"


async def _post_token(
    payload: dict[str, Any], routes: list[Route], *, what: str = "refresh"
) -> dict[str, Any]:
    """POST to xAI's token endpoint, trying each route until one returns 2xx.

    Rotates past network errors and IP/rate blocks. A definitive 4xx (e.g. an
    ``invalid_grant`` from a revoked refresh token) raises :class:`NotRefreshable`
    immediately; exhausting every route raises :class:`RefreshUpstreamError`.
    """
    last_status: int | None = None
    last_reason = "no outbound route available"
    attempt_count = 0
    for route in routes or [Route()]:
        attempt_count += 1
        label = route.proxy_url or "direct"
        try:
            client = await get_pool().get(route, connect_timeout=15.0, read_timeout=30.0)
            resp = await client.post(TOKEN_URL, json=payload, headers=_TOKEN_HEADERS)
        except httpx.HTTPError as exc:
            last_status, last_reason = None, type(exc).__name__
            log.warning("xai_oauth_network_error", op=what, route=label, error=str(exc))
            await _log_token_request(
                op=what,
                route=route,
                status_code=None,
                success=False,
                attempts=attempt_count,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if resp.status_code == 200:
            await _log_token_request(
                op=what,
                route=route,
                status_code=resp.status_code,
                success=True,
                attempts=attempt_count,
                error=None,
            )
            return resp.json()
        last_status, last_reason = resp.status_code, _short_reason(resp)
        log.warning(
            "xai_oauth_http_error",
            op=what,
            route=label,
            status=resp.status_code,
            body=resp.text[:300],
        )
        await _log_token_request(
            op=what,
            route=route,
            status_code=resp.status_code,
            success=False,
            attempts=attempt_count,
            error=f"HTTP {resp.status_code}: {last_reason}",
        )
        if resp.status_code in (403, 408, 425, 429) or resp.status_code >= 500:
            continue  # block / transient — try the next egress IP
        raise NotRefreshable(f"xAI rejected the {what} (HTTP {resp.status_code}: {last_reason}).")
    detail = f"HTTP {last_status}: {last_reason}" if last_status else last_reason
    raise RefreshUpstreamError(
        f"Could not reach xAI's token endpoint via any route (last: {detail}). "
        "Check the provider's proxies and retry."
    )


async def _log_token_request(
    *,
    op: str,
    route: Route,
    status_code: int | None,
    success: bool,
    attempts: int,
    error: str | None,
) -> None:
    model = f"<xai-{op}-token>"
    # A manual "refresh token" action stamps the request log with the operator
    # who triggered it (and the target key/provider); the automatic near-expiry /
    # 401-retry path leaves this unset and logs anonymously.
    actor = refresh_context.get_actor()
    try:
        async with get_database().session() as session:
            session.add(
                RequestLog(
                    model=model,
                    upstream_model=TOKEN_HOST_MODEL,
                    upstream_url=TOKEN_URL,
                    proxy_url=route.proxy_url,
                    req_method="POST",
                    status_code=status_code,
                    success=success,
                    stream=False,
                    attempts=attempts,
                    error=error,
                    user_agent=OAUTH_USER_AGENT,
                    client_type="xai-oauth-refresh" if actor else "xai-oauth",
                    is_opencode=True,
                    user_sub=actor.actor_sub if actor else None,
                    key_id=actor.key_id if actor else None,
                    provider_id=actor.provider_id if actor else None,
                    provider_name=actor.provider_name if actor else None,
                )
            )
    except Exception as exc:  # pragma: no cover - logging must not break OAuth
        log.warning("xai_oauth_request_log_failed", op=op, error=str(exc))


async def resolve_access_token(
    session: AsyncSession,
    key: ApiKey,
    *,
    secret_key: str,
    force_refresh: bool = False,
) -> str:
    """Return a valid access token for an ``xai`` key, refreshing if needed."""
    plaintext = decrypt_secret(key.key_ciphertext, secret=secret_key)
    bundle = parse_bundle(plaintext)

    # Static API key (``xai-…``): nothing to refresh.
    if bundle is None:
        if force_refresh:
            raise NotRefreshable("static API key cannot be refreshed")
        return plaintext

    access = bundle.get("access_token")
    refresh_token = bundle.get("refresh_token")

    # No refresh token: return whatever access token we have, but a missing one
    # is unusable and a forced refresh is impossible.
    if not refresh_token:
        if not access:
            raise NotRefreshable("credential bundle has neither access_token nor refresh_token")
        if force_refresh:
            raise NotRefreshable("no refresh_token in credential bundle")
        return str(access)

    # A refresh-only bundle (sub2api) has no access token yet — always refresh.
    needs_refresh = force_refresh or not access or _near_expiry(bundle)
    if not needs_refresh:
        return str(access)

    async with _lock_for(key.id):
        # Re-read committed state in case a concurrent request just refreshed.
        try:
            await session.refresh(key)
        except Exception as exc:
            log.debug("orm_refresh_skipped", error=str(exc))
        plaintext = decrypt_secret(key.key_ciphertext, secret=secret_key)
        bundle = parse_bundle(plaintext) or bundle
        access = bundle.get("access_token")
        refresh_token = bundle.get("refresh_token") or refresh_token
        if not force_refresh and access and not _near_expiry(bundle):
            return str(access)

        routes = await _select_routes(session)
        new_bundle = await _refresh(str(refresh_token), routes)
        key.key_ciphertext = encrypt_secret(json.dumps(new_bundle), secret=secret_key)
        key.last_checked_at = dt.datetime.now(dt.UTC)
        await session.flush()
        # Commit immediately so the rotated refresh token is durable and visible
        # to other concurrent requests (refresh tokens are single-use/rotating).
        await session.commit()
        log.info("xai_oauth_token_refreshed", key_id=key.id)
        return str(new_bundle["access_token"])


async def _refresh(refresh_token: str, routes: list[Route]) -> dict[str, Any]:
    data = await _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "scope": " ".join(REFRESH_SCOPES),
        },
        routes,
        what="refresh",
    )
    access = data.get("access_token")
    if not access:
        raise NotRefreshable("xAI refresh response was missing the access token.")
    return {
        "access_token": access,
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": time.time() + float(data.get("expires_in", DEFAULT_EXPIRES_IN)),
    }
