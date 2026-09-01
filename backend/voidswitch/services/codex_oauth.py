"""OpenAI Codex subscription login (browser PKCE and device code) and refresh."""

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
from voidswitch.core.security import decrypt_secret, encrypt_secret
from voidswitch.models.db import ApiKey
from voidswitch.services.network import Route, get_pool

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE_URL = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/oauth/token"
DEVICE_CODE_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/token"
DEVICE_VERIFY_URL = f"{AUTH_BASE_URL}/codex/device"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPES = "openid profile email offline_access"
NEAR_EXPIRY_SECONDS = 300
LOGIN_STATE_TTL_SECONDS = 900
OAUTH_HEADERS = {"User-Agent": "codex_cli_rs", "Accept": "application/json"}


class LoginError(Exception):
    """The login was invalid or definitively rejected."""


class LoginUpstreamError(Exception):
    """OpenAI auth could not be reached through any system route."""


class NotRefreshable(Exception):
    """The stored credential has no usable refresh token."""


@dataclass(slots=True)
class _PendingLogin:
    verifier: str
    provider_id: int
    created: float


_pending: dict[str, _PendingLogin] = {}
_locks: dict[int, asyncio.Lock] = {}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def _gc() -> None:
    cutoff = time.time() - LOGIN_STATE_TTL_SECONDS
    for state in [key for key, value in _pending.items() if value.created < cutoff]:
        _pending.pop(state, None)


def begin_login(provider_id: int) -> tuple[str, str]:
    """Begin Codex's loopback browser flow; the redirected URL is pasted back."""
    _gc()
    verifier, challenge = _pkce_pair()
    state = _b64url(secrets.token_bytes(32))
    _pending[state] = _PendingLogin(verifier, provider_id, time.time())
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "audience": "https://api.openai.com/v1",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_cli_rs",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}", state


def extract_code(raw: str) -> tuple[str, str | None]:
    raw = (raw or "").strip()
    if not raw:
        raise LoginError("No authorization code was provided.")
    if "://" in raw or "code=" in raw:
        query = parse_qs(urlparse(raw).query or raw.split("?", 1)[-1])
        if query.get("error"):
            raise LoginError(str(query["error"][0]))
        if not query.get("code"):
            raise LoginError("Could not find a `code` in the pasted callback URL.")
        return query["code"][0], query.get("state", [None])[0]
    return raw, None


async def _select_routes(session: AsyncSession | None) -> list[Route]:
    if session is None:
        return [Route()]
    from voidswitch.services import routing

    return [route for route, _ in await routing.system_routes(session)] or [Route()]


def _reason(response: httpx.Response) -> str:
    with contextlib.suppress(Exception):
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("type") or "rejected")
            return str(body.get("error_description") or error or "rejected")
    return "rejected"


async def _post(
    url: str,
    routes: list[Route],
    *,
    form: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    pending_ok: bool = False,
) -> dict[str, Any] | None:
    last = "no outbound route available"
    for route in routes or [Route()]:
        try:
            client = await get_pool().get(route, connect_timeout=15, read_timeout=30)
            response = await client.post(url, data=form, json=body, headers=OAUTH_HEADERS)
        except httpx.HTTPError as exc:
            last = type(exc).__name__
            continue
        if response.status_code == 200:
            try:
                result = response.json()
            except ValueError:
                # A proxy/login edge occasionally returns an HTML or empty 200.
                # Treat that as a broken route, not an unhandled application error.
                last = "HTTP 200: invalid JSON response"
                continue
            return result if isinstance(result, dict) else {}
        # Device authorization reports "not approved yet" as a 403. Do not
        # confuse an unrelated edge/proxy 403 with a normal pending poll.
        reason = _reason(response)
        if pending_ok and response.status_code == 403 and "pending" in reason.lower():
            return None
        last = f"HTTP {response.status_code}: {reason}"
        if response.status_code not in (403, 408, 425, 429) and response.status_code < 500:
            raise LoginError(f"OpenAI rejected the login ({last}).")
    raise LoginUpstreamError(f"Could not reach OpenAI authentication (last: {last}).")


def _jwt_claims(token: object) -> dict[str, Any]:
    try:
        part = str(token).split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _make_bundle(data: dict[str, Any], old_refresh: str | None = None) -> dict[str, Any]:
    access = data.get("access_token")
    if not access:
        raise LoginError("OpenAI's token response was missing the access token.")
    claims = _jwt_claims(data.get("id_token") or access)
    auth = claims.get("https://api.openai.com/auth", {})
    account_id = auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
    return {
        "access_token": access,
        "refresh_token": data.get("refresh_token") or old_refresh,
        "id_token": data.get("id_token"),
        "account_id": account_id,
        "expires_at": time.time() + float(data.get("expires_in", 3600)),
        "scopes": str(data.get("scope") or SCOPES).split(),
    }


async def _exchange(code: str, verifier: str, routes: list[Route]) -> dict[str, Any]:
    data = await _post(
        TOKEN_URL,
        routes,
        form={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert data is not None
    return _make_bundle(data)


async def complete_login(
    code_input: str,
    state: str,
    *,
    provider_id: int,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    _gc()
    pending = _pending.get(state)
    if pending is None:
        raise LoginError("Unknown or expired login. Start sign-in again.")
    if pending.provider_id != provider_id:
        _pending.pop(state, None)
        raise LoginError("This login was started for a different provider.")
    code, embedded_state = extract_code(code_input)
    if embedded_state is not None and embedded_state != state:
        _pending.pop(state, None)
        raise LoginError("State mismatch — the pasted URL does not match this login.")
    try:
        bundle = await _exchange(code, pending.verifier, await _select_routes(session))
    except LoginUpstreamError:
        raise  # preserve state so a transient route failure can be retried
    except Exception:
        _pending.pop(state, None)
        raise
    _pending.pop(state, None)
    return bundle


async def begin_device_login(session: AsyncSession | None = None) -> dict[str, Any]:
    data = await _post(
        DEVICE_CODE_URL,
        await _select_routes(session),
        body={"client_id": CLIENT_ID},
    )
    assert data is not None
    if not data.get("device_auth_id") or not data.get("user_code"):
        raise LoginError("OpenAI returned an invalid device-login response.")
    return {
        "device_auth_id": data["device_auth_id"],
        "user_code": data["user_code"],
        "verification_url": data.get("verification_uri") or DEVICE_VERIFY_URL,
        "interval": max(1, int(data.get("interval", 5))),
        "expires_in": int(data.get("expires_in", 900)),
    }


async def complete_device_login(
    device_auth_id: str,
    user_code: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Poll the device grant once; return None until the user approves it."""
    routes = await _select_routes(session)
    grant = await _post(
        DEVICE_TOKEN_URL,
        routes,
        body={"device_auth_id": device_auth_id, "user_code": user_code},
        pending_ok=True,
    )
    if grant is None:
        return None
    code, verifier = grant.get("authorization_code"), grant.get("code_verifier")
    if not code or not verifier:
        raise LoginError("OpenAI returned an invalid device authorization.")
    return await _exchange(str(code), str(verifier), routes)


def parse_bundle(plaintext: str) -> dict[str, Any] | None:
    try:
        value = json.loads(plaintext)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(value, dict) and (value.get("access_token") or value.get("refresh_token")):
        return value
    return None


def _near_expiry(bundle: dict[str, Any]) -> bool:
    try:
        return time.time() + NEAR_EXPIRY_SECONDS >= float(bundle.get("expires_at", 0))
    except (TypeError, ValueError):
        return False


async def resolve_access_token(
    session: AsyncSession,
    key: ApiKey,
    *,
    secret_key: str,
    force_refresh: bool = False,
) -> str:
    plaintext = decrypt_secret(key.key_ciphertext, secret=secret_key)
    bundle = parse_bundle(plaintext)
    if bundle is None:
        if force_refresh:
            raise NotRefreshable("static token cannot be refreshed")
        return plaintext
    access, refresh_token = bundle.get("access_token"), bundle.get("refresh_token")
    if not refresh_token:
        if force_refresh or not access:
            raise NotRefreshable("credential bundle has no refresh token")
        return str(access)
    if access and not force_refresh and not _near_expiry(bundle):
        return str(access)

    lock = _locks.setdefault(key.id, asyncio.Lock())
    async with lock, get_database().session() as refresh_session:
        fresh_key = await refresh_session.get(ApiKey, key.id)
        if fresh_key is None:
            raise NotRefreshable("key no longer exists")
        fresh = parse_bundle(decrypt_secret(fresh_key.key_ciphertext, secret=secret_key)) or bundle
        if fresh.get("access_token") and not force_refresh and not _near_expiry(fresh):
            return str(fresh["access_token"])
        data = await _post(
            TOKEN_URL,
            await _select_routes(refresh_session),
            form={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": str(fresh.get("refresh_token") or refresh_token),
            },
        )
        assert data is not None
        rotated = _make_bundle(data, str(fresh.get("refresh_token") or refresh_token))
        fresh_key.key_ciphertext = encrypt_secret(json.dumps(rotated), secret=secret_key)
        fresh_key.last_checked_at = dt.datetime.now(dt.UTC)
        return str(rotated["access_token"])
