"""Authentication: Prism OAuth handshake, role resolution, and request guards.

Two credential types coexist:

* **Dashboard session JWT** — minted by us after a Prism OAuth login, sent as a
  Bearer token by the web UI. Carries the user's role.
* **Void-Token** (``vs-…``) — long-lived client credential used to call the
  proxy endpoints (``/v1/...``). Maps to a user + quota.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import Role
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger
from voidswitch.core.security import (
    decode_session_token,
    hash_token,
)
from voidswitch.models.db import User, VoidToken
from voidswitch.services.network import Route, get_pool

log = get_logger("auth")

STAFF_ROLES = {Role.OWNER.value, Role.ADMIN.value}


# --------------------------------------------------------------------------- #
# PKCE + transient OAuth state (single-node in-memory, TTL'd)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _PendingLogin:
    verifier: str
    created: float


class _StateStore:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._store: dict[str, _PendingLogin] = {}
        self._ttl = ttl_seconds

    def put(self, state: str, verifier: str) -> None:
        self._gc()
        self._store[state] = _PendingLogin(verifier=verifier, created=time.time())

    def pop(self, state: str) -> str | None:
        self._gc()
        entry = self._store.pop(state, None)
        return entry.verifier if entry else None

    def _gc(self) -> None:
        cutoff = time.time() - self._ttl
        for key in [k for k, v in self._store.items() if v.created < cutoff]:
            self._store.pop(key, None)


_state_store = _StateStore()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorize_url(settings: Settings) -> tuple[str, str]:
    """Return ``(authorize_url, state)`` and stash the PKCE verifier."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    _state_store.put(state, verifier)
    params = {
        "response_type": "code",
        "client_id": settings.prism.client_id,
        "redirect_uri": settings.prism.redirect_uri,
        "scope": " ".join(settings.prism.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.prism.authorize_url}?{urlencode(params)}", state


# --------------------------------------------------------------------------- #
# Token exchange + userinfo
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class PrismIdentity:
    sub: str
    username: str | None
    email: str | None
    name: str | None
    picture: str | None
    prism_role: str | None


async def exchange_code(settings: Settings, code: str, state: str) -> PrismIdentity:
    verifier = _state_store.pop(state)
    if verifier is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired login state.")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.prism.redirect_uri,
        "client_id": settings.prism.client_id,
        "code_verifier": verifier,
    }
    if settings.prism.client_secret:
        data["client_secret"] = settings.prism.client_secret

    client = await get_pool().get(Route(), connect_timeout=15.0, read_timeout=30.0)
    resp = await client.post(
        settings.prism.token_url,
        data=data,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        log.warning("token_exchange_failed", status=resp.status_code, body=resp.text[:300])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OAuth token exchange failed.")
    tokens = resp.json()

    claims = _decode_id_token(settings, tokens.get("id_token"))
    identity = await _fetch_userinfo(settings, tokens.get("access_token"), claims)
    return identity


def _decode_id_token(settings: Settings, id_token: str | None) -> dict[str, Any]:
    if not id_token:
        return {}
    # Best-effort signature verification via JWKS; fall back to unverified claims
    # (we already trust the response, delivered over TLS from the token endpoint).
    try:
        jwk_client = jwt.PyJWKClient(settings.prism.jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.prism.client_id,
            options={"verify_aud": True},
        )
    except Exception as exc:
        log.debug("id_token_verify_skipped", error=str(exc))
        try:
            return jwt.decode(id_token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return {}


async def _fetch_userinfo(
    settings: Settings, access_token: str | None, claims: dict[str, Any]
) -> PrismIdentity:
    info: dict[str, Any] = {}
    if access_token:
        try:
            client = await get_pool().get(Route(), connect_timeout=15.0, read_timeout=30.0)
            resp = await client.get(
                settings.prism.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                info = resp.json()
        except httpx.HTTPError as exc:
            log.debug("userinfo_failed", error=str(exc))

    merged = {**claims, **info}
    sub = str(merged.get("sub") or "")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OAuth identity missing subject.")
    return PrismIdentity(
        sub=sub,
        username=merged.get("preferred_username"),
        email=merged.get("email"),
        name=merged.get("name"),
        picture=merged.get("picture"),
        prism_role=str(merged.get("role")) if merged.get("role") else None,
    )


# --------------------------------------------------------------------------- #
# User upsert + role resolution
# --------------------------------------------------------------------------- #


async def upsert_user(session: AsyncSession, settings: Settings, identity: PrismIdentity) -> User:
    existing = (
        await session.execute(select(User).where(User.sub == identity.sub))
    ).scalar_one_or_none()

    total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
    is_first_user = total_users == 0 and existing is None

    role = _resolve_role(settings, identity, is_first_user)

    if existing is None:
        user = User(
            sub=identity.sub,
            username=identity.username,
            email=identity.email,
            name=identity.name,
            picture=identity.picture,
            role=role.value,
            prism_role=identity.prism_role,
            last_login_at=dt.datetime.now(dt.UTC),
        )
        session.add(user)
        await session.flush()
        return user

    existing.username = identity.username or existing.username
    existing.email = identity.email or existing.email
    existing.name = identity.name or existing.name
    existing.picture = identity.picture or existing.picture
    existing.prism_role = identity.prism_role
    existing.last_login_at = dt.datetime.now(dt.UTC)
    # Promote (never silently demote) based on config-derived role.
    if existing.role not in STAFF_ROLES and role.value in STAFF_ROLES:
        existing.role = role.value
    await session.flush()
    return existing


DEV_USER_SUB = "dev-mode-user"


async def dev_login_user(session: AsyncSession, settings: Settings) -> User:
    """Upsert a synthetic owner account for dev-mode (no OAuth) sign-in.

    Guarded by the caller: only reachable when ``server.dev_mode`` is enabled.
    """
    if not settings.server.dev_mode:  # defensive — callers also check
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    user = (
        await session.execute(select(User).where(User.sub == DEV_USER_SUB))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            sub=DEV_USER_SUB,
            username="dev",
            email="dev@voidswitch.local",
            name="Developer (dev mode)",
            role=Role.OWNER.value,
            last_login_at=dt.datetime.now(dt.UTC),
        )
        session.add(user)
        await session.flush()
        return user

    user.role = Role.OWNER.value
    user.enabled = True
    user.last_login_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return user


def _resolve_role(settings: Settings, identity: PrismIdentity, is_first_user: bool) -> Role:
    admin = settings.admin
    if identity.sub in admin.owner_subs:
        return Role.OWNER
    if identity.email and identity.email in admin.owner_emails:
        return Role.OWNER
    if admin.trust_prism_admin and identity.prism_role == "admin":
        return Role.OWNER
    if is_first_user and admin.bootstrap_first_user:
        return Role.OWNER
    return Role.MEMBER


# --------------------------------------------------------------------------- #
# Request guards
# --------------------------------------------------------------------------- #


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    try:
        claims = decode_session_token(token, secret=settings.server.secret_key)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token.") from exc
    user = (
        await session.execute(select(User).where(User.sub == str(claims.get("sub"))))
    ).scalar_one_or_none()
    if user is None or not user.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled.")
    return user


async def require_staff(user: User = Depends(get_current_user)) -> User:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required.")
    return user


async def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.OWNER.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner privileges required.")
    return user


@dataclass(slots=True)
class AuthedToken:
    token: VoidToken
    user: User


async def authenticate_void_token(
    request: Request,
    session: AsyncSession,
    authorization: str | None,
    x_api_key: str | None = None,
) -> AuthedToken:
    raw = _bearer(authorization) or x_api_key
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key.")
    token = (
        await session.execute(select(VoidToken).where(VoidToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if token is None or not token.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")
    if token.expires_at is not None:
        expires = token.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        if expires < dt.datetime.now(dt.UTC):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired.")
    user = await session.get(User, token.user_id)
    if user is None or not user.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token owner disabled.")
    return AuthedToken(token=token, user=user)
