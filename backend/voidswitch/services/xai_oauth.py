"""xAI (Grok) OAuth login + token refresh for the ``xai`` / ``grok-build`` adapters.

Like :mod:`voidswitch.services.oauth_tokens` (Claude Code), this module
implements *both* halves of the flow:

* the interactive **login** half (:func:`begin_login` / :func:`extract_code` /
  :func:`complete_login`) — a PKCE authorization-code flow against xAI's auth
  server used to sign a Grok Build subscription in from the dashboard; and
* the **refresh** half (:func:`resolve_access_token`) — keeping a stored OAuth
  bundle alive by exchanging its rotating ``refresh_token`` for a fresh
  ``access_token``.

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
import base64
import contextlib
import datetime as dt
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

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

# --- Interactive login (Grok Build subscription) -----------------------------
# The grok-cli public client uses a PKCE authorization-code flow against xAI's
# hosted auth server. The redirect lands on a fixed loopback address that the CLI
# would normally catch with a throwaway local server; in VoidSwitch's server-side
# flow the operator instead copies the full redirected URL out of the browser's
# address bar and pastes it back (``extract_code`` parses ``?code=&state=``).
AUTHORIZE_URL = "https://auth.x.ai/oauth2/authorize"
REDIRECT_URI = "http://127.0.0.1:56121/callback"
# Grok Build entitlement. The CLI-chat-proxy backend (cli-chat-proxy.grok.com)
# rejects tokens that lack ``api:access`` with HTTP 403
# ``{"code":"permission-denied","error":"OAuth2 token missing required scope:
# api:access"}``, so it MUST be requested at authorization time. OAuth refresh can
# only narrow scopes, never add them, so an ``api:access``-less login token can
# never be upgraded — the scope has to be granted in the authorize request.
LOGIN_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "grok-cli:access",
    "api:access",
)
LOGIN_STATE_TTL_SECONDS = 600  # pending logins expire after 10 minutes

# xAI's auth endpoint, like Claude's, is picky about datacenter IPs and default
# user-agents; send a CLI-style UA and route through the configured proxies.
OAUTH_USER_AGENT = "grok-cli/1.0.0"
_TOKEN_HEADERS = {"User-Agent": OAUTH_USER_AGENT}

_locks: dict[int, asyncio.Lock] = {}


class NotRefreshable(Exception):
    """Raised when a force-refresh is requested but the key cannot be refreshed."""


class RefreshUpstreamError(Exception):
    """Every egress route failed to reach xAI's token endpoint."""


class LoginError(Exception):
    """A user-correctable or definitively-rejected login (maps to HTTP 400)."""


class LoginUpstreamError(Exception):
    """Every egress route failed to reach xAI during login (maps to HTTP 502)."""


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
    payload: dict[str, Any],
    routes: list[Route],
    *,
    what: str = "refresh",
    reject_exc: type[Exception] = NotRefreshable,
    exhausted_exc: type[Exception] = RefreshUpstreamError,
) -> dict[str, Any]:
    """POST to xAI's token endpoint, trying each route until one returns 2xx.

    xAI's ``/oauth2/token`` endpoint is a strict OAuth2 server: it requires the
    body be ``application/x-www-form-urlencoded`` (a JSON body is rejected with
    "Form requests must have Content-Type: application/x-www-form-urlencoded"),
    so the payload is sent as form data, not JSON.

    Rotates past network errors and IP/rate blocks. A definitive 4xx (e.g. an
    ``invalid_grant`` from a revoked refresh token or a spent authorization code)
    raises ``reject_exc`` immediately; exhausting every route raises
    ``exhausted_exc``. Callers pass the login exception pair
    (:class:`LoginError` / :class:`LoginUpstreamError`) for the login exchange.
    """
    last_status: int | None = None
    last_reason = "no outbound route available"
    attempt_count = 0
    for route in routes or [Route()]:
        attempt_count += 1
        label = route.proxy_url or "direct"
        try:
            client = await get_pool().get(route, connect_timeout=15.0, read_timeout=30.0)
            resp = await client.post(TOKEN_URL, data=payload, headers=_TOKEN_HEADERS)
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
        raise reject_exc(f"xAI rejected the {what} (HTTP {resp.status_code}: {last_reason}).")
    detail = f"HTTP {last_status}: {last_reason}" if last_status else last_reason
    raise exhausted_exc(
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
                    started_at=dt.datetime.now(dt.UTC),
                    finished_at=dt.datetime.now(dt.UTC),
                    req_status="completed",
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

    async with _lock_for(key.id), get_database().session() as rot_session:
        # Re-read committed state in a *dedicated* session and rotate there. The
        # caller's ``session`` is shared (the request transaction / the dispatcher)
        # and may carry unrelated pending writes; committing it here would persist
        # those mid-request and split the request into two transactions. Rotating
        # in its own transaction keeps the single-use refresh token durable while
        # leaving the caller's transaction intact.
        fresh_key = await rot_session.get(ApiKey, key.id)
        if fresh_key is None:
            raise NotRefreshable("key no longer exists")
        plaintext = decrypt_secret(fresh_key.key_ciphertext, secret=secret_key)
        bundle = parse_bundle(plaintext) or bundle
        access = bundle.get("access_token")
        refresh_token = bundle.get("refresh_token") or refresh_token
        if not force_refresh and access and not _near_expiry(bundle):
            return str(access)
        routes = await _select_routes(rot_session)
        new_bundle = await _refresh(str(refresh_token), routes)
        fresh_key.key_ciphertext = encrypt_secret(json.dumps(new_bundle), secret=secret_key)
        fresh_key.last_checked_at = dt.datetime.now(dt.UTC)
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


# --- Interactive login (PKCE authorization-code flow) ------------------------


def _b64url(raw: bytes) -> str:
    """URL-safe base64 without padding (PKCE / state encoding)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    """Return a ``(verifier, challenge)`` PKCE pair using the S256 method."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


@dataclass(slots=True)
class _PendingLogin:
    verifier: str
    provider_id: int
    created: float


class _StateStore:
    """In-memory CSRF-state -> pending-login map with a short TTL.

    Login state is intentionally *not* persisted: a pending login is only valid
    within a single browser round-trip and must not survive a restart.
    """

    def __init__(self, ttl: float = LOGIN_STATE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._items: dict[str, _PendingLogin] = {}

    def _gc(self) -> None:
        cutoff = time.time() - self._ttl
        stale = [state for state, item in self._items.items() if item.created < cutoff]
        for state in stale:
            self._items.pop(state, None)

    def put(self, state: str, verifier: str, provider_id: int) -> None:
        self._gc()
        self._items[state] = _PendingLogin(
            verifier=verifier, provider_id=provider_id, created=time.time()
        )

    def peek(self, state: str) -> _PendingLogin | None:
        self._gc()
        return self._items.get(state)

    def discard(self, state: str) -> None:
        self._items.pop(state, None)


_login_states = _StateStore()


def begin_login(provider_id: int) -> tuple[str, str]:
    """Start a Grok Build OAuth login; return ``(authorize_url, state)``.

    The caller shows ``authorize_url`` to the operator, who signs in and is then
    redirected to :data:`REDIRECT_URI` (a loopback address that will not load).
    The operator copies the full redirected URL back for :func:`complete_login`.
    """
    verifier, challenge = _pkce_pair()
    state = _b64url(secrets.token_bytes(32))
    _login_states.put(state, verifier, provider_id)
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(LOGIN_SCOPES),
        "state": state,
        "nonce": secrets.token_hex(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}", state


def extract_code(raw: str) -> tuple[str, str | None]:
    """Parse a pasted authorization code out of whatever the operator provides.

    Accepts the full redirected callback URL (``…/callback?code=…&state=…``), a
    bare query string, a ``code#state`` fragment, or just the code. Returns
    ``(code, embedded_state_or_None)``.
    """
    raw = (raw or "").strip()
    if not raw:
        raise LoginError("No authorization code was provided.")
    if "://" in raw or "code=" in raw:
        query = urlparse(raw).query or raw.split("?", 1)[-1]
        params = parse_qs(query)
        codes = params.get("code")
        if not codes:
            raise LoginError("Could not find a `code` in the pasted URL.")
        states = params.get("state")
        return codes[0], (states[0] if states else None)
    if "#" in raw:
        code, _, state = raw.partition("#")
        return code.strip(), (state.strip() or None)
    return raw, None


async def complete_login(
    code_input: str,
    state: str,
    *,
    provider_id: int,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Exchange a pasted authorization code for an OAuth credential bundle."""
    pending = _login_states.peek(state)
    if pending is None:
        raise LoginError("Unknown or expired login. Start the sign-in again.")
    if pending.provider_id != provider_id:
        _login_states.discard(state)
        raise LoginError("This login was started for a different provider.")

    code, embedded_state = extract_code(code_input)
    if embedded_state is not None and embedded_state != state:
        _login_states.discard(state)
        raise LoginError("State mismatch — the pasted URL does not match this login.")

    routes = await _select_routes(session)
    try:
        bundle = await _exchange_code(code, pending.verifier, routes)
    except LoginError:
        # A definitive rejection (spent/invalid code): burn the state so the user
        # restarts cleanly. Transient LoginUpstreamError keeps the state for retry.
        _login_states.discard(state)
        raise
    _login_states.discard(state)
    return bundle


async def _exchange_code(code: str, verifier: str, routes: list[Route]) -> dict[str, Any]:
    data = await _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        },
        routes,
        what="exchange",
        reject_exc=LoginError,
        exhausted_exc=LoginUpstreamError,
    )
    access = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access or not refresh_token:
        raise LoginError("xAI's login response was missing tokens. Try signing in again.")
    scope = data.get("scope")
    scopes = scope.split() if isinstance(scope, str) and scope else list(LOGIN_SCOPES)
    return {
        "access_token": access,
        "refresh_token": refresh_token,
        "expires_at": time.time() + float(data.get("expires_in", DEFAULT_EXPIRES_IN)),
        "scopes": scopes,
    }
