"""Claude Code subscription OAuth — full login + token lifecycle.

This module implements both halves of the Claude Code OAuth flow:

* **Login** (:func:`begin_login` / :func:`complete_login`) — the PKCE
  authorization-code grant. We build the same authorize URL the CLI does, the
  user approves it in a browser, and we exchange the returned code for a
  credential bundle. The *manual* redirect is used (Claude shows the user a
  ``code#state`` to paste back), the only browser-free option for a server.
* **Refresh** (:func:`resolve_access_token`) — auto-refresh near expiry and
  force-refresh on a 401, mirroring the CLI, re-encrypting the rotated bundle
  back into the key so the single-use refresh token persists.

A ``claude-code`` provider key may be stored either as:

* a plain long-lived token (``claude setup-token``) — used as-is, no refresh; or
* an OAuth credential bundle JSON ``{"access_token", "refresh_token",
  "expires_at"}`` — produced by :func:`complete_login` (or pasted from a Claude
  Code credentials file) — which is auto-refreshed as above.

Constants verified against the Claude Code source (``cli.js``: ``Lc$`` builds the
authorize URL, ``qH6`` exchanges the code, ``L_$`` refreshes) and the
``claude_review`` reference ``oauth.rs``.
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

log = get_logger("oauth")

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
TOKEN_HOST_MODEL = "<cc-token>"
# Subscription (Pro/Max) login uses the claude.ai authorize host. The manual
# redirect lands on a Claude-hosted page that prints ``code#state`` to copy.
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
MANUAL_REDIRECT_URL = "https://platform.claude.com/oauth/code/callback"
REFRESH_SCOPES = (
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
)
# Scopes requested at login — a superset of REFRESH_SCOPES, additionally asking
# for ``org:create_api_key`` exactly as the CLI's subscription login does.
LOGIN_SCOPES = ("org:create_api_key", *REFRESH_SCOPES)
NEAR_EXPIRY_SECONDS = 300  # refresh 5 minutes before expiry, like the CLI
LOGIN_STATE_TTL_SECONDS = 600  # a started login must be completed within 10 min

# Claude's auth endpoints reject requests from many datacenter IPs and from
# clients with a default (e.g. ``python-httpx``) user-agent. We send a CLI-style
# UA and route through the configured proxies, exactly like real Claude Code.
OAUTH_USER_AGENT = "claude-cli/2.1.150"
_TOKEN_HEADERS = {"User-Agent": OAUTH_USER_AGENT}

_locks: dict[int, asyncio.Lock] = {}


class NotRefreshable(Exception):
    """Raised when a force-refresh is requested but the key cannot be refreshed."""


def _lock_for(key_id: int) -> asyncio.Lock:
    lock = _locks.get(key_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key_id] = lock
    return lock


# --------------------------------------------------------------------------- #
# Authorization-code + PKCE login (manual flow)
# --------------------------------------------------------------------------- #


class LoginError(Exception):
    """A user-correctable problem that should NOT be retried with the same code.

    Expired/unknown state, a login started for a different provider, a malformed
    pasted code, a CSRF state mismatch, or a *definitive* upstream rejection
    (e.g. ``invalid_grant``). Surfaced as HTTP 400; the login state is burned.
    """


class LoginUpstreamError(Exception):
    """A transient failure reaching the token endpoint.

    A network error, or every egress route returned a block/5xx. The
    authorization code was never accepted, so the login state is preserved and
    the user may retry the same paste once egress recovers. Surfaced as HTTP 502.
    """


@dataclass(slots=True)
class _PendingLogin:
    verifier: str
    provider_id: int
    created: float


class _StateStore:
    """In-memory, TTL'd map of OAuth ``state`` → pending login.

    Each entry binds the PKCE verifier to the provider the login was started
    for. Single-node, mirroring the dashboard's Prism login store
    (:mod:`voidswitch.core.auth`). A login not completed within the TTL is
    garbage-collected on the next access.
    """

    def __init__(self, ttl_seconds: int = LOGIN_STATE_TTL_SECONDS) -> None:
        self._store: dict[str, _PendingLogin] = {}
        self._ttl = ttl_seconds

    def put(self, state: str, verifier: str, provider_id: int) -> None:
        self._gc()
        self._store[state] = _PendingLogin(
            verifier=verifier, provider_id=provider_id, created=time.time()
        )

    def peek(self, state: str) -> _PendingLogin | None:
        """Return the pending login without consuming it (consume on completion)."""
        self._gc()
        return self._store.get(state)

    def discard(self, state: str) -> None:
        self._store.pop(state, None)

    def _gc(self) -> None:
        cutoff = time.time() - self._ttl
        for key in [k for k, v in self._store.items() if v.created < cutoff]:
            self._store.pop(key, None)


_login_states = _StateStore()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` — a base64url 32-byte verifier and its
    S256 challenge, exactly as the Claude Code CLI derives them."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def begin_login(provider_id: int) -> tuple[str, str]:
    """Start a login for ``provider_id``. Stash a fresh PKCE verifier (bound to
    that provider) and return ``(authorize_url, state)``.

    The URL mirrors Claude Code's ``Lc$`` builder: ``code=true`` + client id +
    ``response_type=code`` + the manual redirect + the full login scopes + the
    S256 challenge + an anti-CSRF ``state``.
    """
    verifier, challenge = _pkce_pair()
    state = _b64url(secrets.token_bytes(32))
    _login_states.put(state, verifier, provider_id)
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": MANUAL_REDIRECT_URL,
        "scope": " ".join(LOGIN_SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}", state


def extract_code(raw: str) -> tuple[str, str | None]:
    """Pull ``(code, embedded_state?)`` out of whatever the user pasted.

    Accepts the ``code#state`` string Claude's manual page shows, a full
    redirect URL (``…/callback?code=…&state=…``), or a bare code — mirroring the
    reference ``extract_code_from_input``.
    """
    raw = raw.strip()
    if not raw:
        raise LoginError("No authorization code provided.")
    # Full or partial URL carrying query parameters.
    if "://" in raw or "code=" in raw:
        with contextlib.suppress(ValueError):
            qs = parse_qs(urlparse(raw).query)
            if qs.get("code"):
                state = qs["state"][0] if qs.get("state") else None
                return qs["code"][0], state
    # "code#state" form.
    if "#" in raw:
        code, _, state = raw.partition("#")
        if code and state:
            return code, state
    # Bare code.
    return raw, None


async def complete_login(
    code_input: str,
    state: str,
    *,
    provider_id: int,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Exchange a pasted authorization code for a credential bundle.

    Validates the login ``state`` (CSRF) against the stashed PKCE verifier, that
    it was issued for ``provider_id``, and — when the paste embeds its own state
    — that the two agree. The exchange is routed through the configured proxies
    (``session`` supplied) so it leaves from the same egress as inference
    traffic; without a session it goes direct.

    On success or a definitive rejection the login state is burned; on a
    transient upstream failure (:class:`LoginUpstreamError`) it is preserved so
    the user can retry the same code once egress recovers. Returns a bundle
    shaped exactly like :func:`parse_bundle` expects.
    """
    pending = _login_states.peek(state)
    if pending is None:
        raise LoginError("Unknown or expired login. Start the sign-in again.")
    if pending.provider_id != provider_id:
        _login_states.discard(state)
        raise LoginError("This sign-in was started for a different provider.")
    code, embedded_state = extract_code(code_input)
    if embedded_state is not None and embedded_state != state:
        _login_states.discard(state)
        raise LoginError("State mismatch — please restart the sign-in.")

    routes = await _select_routes(session)
    try:
        bundle = await _exchange_code(code, pending.verifier, state, routes)
    except LoginError:
        # Definitive rejection / malformed response — the code is spent; burn it.
        _login_states.discard(state)
        raise
    # A transient LoginUpstreamError propagates with the state intact for a retry.
    _login_states.discard(state)
    return bundle


async def _exchange_code(
    code: str, verifier: str, state: str, routes: list[Route]
) -> dict[str, Any]:
    data = await _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": MANUAL_REDIRECT_URL,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
            "state": state,
        },
        routes,
        what="exchange",
    )
    if not data.get("access_token") or not data.get("refresh_token"):
        raise LoginError("Token exchange response was missing the access/refresh token.")
    scope = data.get("scope") or ""
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + float(data.get("expires_in", 3600)),
        "scopes": scope.split() if scope else list(LOGIN_SCOPES),
    }


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
                return err
    return "rejected"


async def _post_token(
    payload: dict[str, Any], routes: list[Route], *, what: str = "token"
) -> dict[str, Any]:
    """POST to the OAuth token endpoint, trying each route until one returns 2xx.

    Rotates past network errors and IP/rate blocks (one proxy's IP may be banned
    while another's is fine). A definitive 4xx (bad code / ``invalid_grant``)
    raises :class:`LoginError` immediately; exhausting every route raises
    :class:`LoginUpstreamError`. The full upstream status/body is logged
    server-side; the raised messages stay concise and carry no raw body.
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
            log.warning("oauth_token_network_error", op=what, route=label, error=str(exc))
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
            "oauth_token_http_error",
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
        raise LoginError(f"Claude rejected the {what} (HTTP {resp.status_code}: {last_reason}).")
    detail = f"HTTP {last_status}: {last_reason}" if last_status else last_reason
    raise LoginUpstreamError(
        f"Could not reach Claude's token endpoint via any route (last: {detail}). "
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
    model = f"<cc-{op}-token>"
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
                    client_type="claude-code-oauth-refresh" if actor else "claude-code-oauth",
                    is_opencode=True,
                    user_sub=actor.actor_sub if actor else None,
                    key_id=actor.key_id if actor else None,
                    provider_id=actor.provider_id if actor else None,
                    provider_name=actor.provider_name if actor else None,
                )
            )
    except Exception as exc:  # pragma: no cover - logging must not break OAuth
        log.warning("oauth_token_request_log_failed", op=op, error=str(exc))


def parse_bundle(plaintext: str) -> dict[str, Any] | None:
    """Return the OAuth bundle if ``plaintext`` is one, else None (static token)."""
    try:
        data = json.loads(plaintext)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "access_token" in data:
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


async def resolve_access_token(
    session: AsyncSession,
    key: ApiKey,
    *,
    secret_key: str,
    force_refresh: bool = False,
) -> str:
    """Return a valid access token for a ``claude-code`` key, refreshing if needed."""
    plaintext = decrypt_secret(key.key_ciphertext, secret=secret_key)
    bundle = parse_bundle(plaintext)

    # Static token (setup-token): nothing to refresh.
    if bundle is None:
        if force_refresh:
            raise NotRefreshable("static token cannot be refreshed")
        return plaintext
    if not bundle.get("refresh_token"):
        if force_refresh:
            raise NotRefreshable("no refresh_token in credential bundle")
        return str(bundle["access_token"])

    if not (force_refresh or _near_expiry(bundle)):
        return str(bundle["access_token"])

    async with _lock_for(key.id):
        # Re-read committed state in case a concurrent request just refreshed.
        try:
            await session.refresh(key)
        except Exception as exc:
            log.debug("orm_refresh_skipped", error=str(exc))
        plaintext = decrypt_secret(key.key_ciphertext, secret=secret_key)
        bundle = parse_bundle(plaintext) or bundle
        if not force_refresh and not _near_expiry(bundle):
            return str(bundle["access_token"])

        routes = await _select_routes(session)
        new_bundle = await _refresh(str(bundle["refresh_token"]), routes)
        key.key_ciphertext = encrypt_secret(json.dumps(new_bundle), secret=secret_key)
        key.last_checked_at = dt.datetime.now(dt.UTC)
        await session.flush()
        # Commit immediately so the rotated refresh token is durable and visible
        # to other concurrent requests (refresh tokens are single-use/rotating).
        await session.commit()
        log.info("oauth_token_refreshed", key_id=key.id)
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
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": time.time() + float(data.get("expires_in", 3600)),
    }
