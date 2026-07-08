"""Token generation, hashing, and dashboard session JWTs."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

import jwt
from cryptography.fernet import Fernet, InvalidToken

VOID_TOKEN_PREFIX = "vs-"
# Per-provider key-management API credential. A distinct prefix keeps it visually
# separable from client-facing Void-Tokens (``vs-…``).
PROVIDER_KEY_API_PREFIX = "vsk-"
# Emergency dashboard login credential. Staff users can keep one as a fallback
# when Prism/OAuth is temporarily unreachable.
LOGIN_TOKEN_PREFIX = "vsl-"


def generate_void_token() -> str:
    """A high-entropy client-facing token. Prefixed for easy identification."""
    return f"{VOID_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def generate_provider_api_token() -> str:
    """A high-entropy per-provider key-management token (``vsk-…``)."""
    return f"{PROVIDER_KEY_API_PREFIX}{secrets.token_urlsafe(32)}"


def generate_login_token() -> str:
    """A high-entropy dashboard login token (``vsl-…``), shown only once."""
    return f"{LOGIN_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    """Deterministic SHA-256 hash for constant-time DB lookup of secrets.

    Tokens are 256-bit random, so a plain salted hash is sufficient (no need for
    a slow KDF — there is nothing to brute-force).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_fingerprint(token: str) -> str:
    """Short, non-reversible label safe to show in UIs/logs (last 4 + hash head)."""
    tail = token[-4:] if len(token) >= 4 else token
    head = hash_token(token)[:6]
    return f"{head}…{tail}"


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_session_token(
    *,
    secret: str,
    subject: str,
    extra: dict[str, object] | None = None,
    ttl_minutes: int = 720,
) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, object] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": "voidswitch",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_session_token(token: str, *, secret: str) -> dict[str, object]:
    """Decode and validate a dashboard session JWT. Raises ``jwt.PyJWTError``."""
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer="voidswitch",
        options={"require": ["exp", "iat", "sub"]},
    )


# The OAuth ``state`` parameter is a short-lived, signed JWT that *carries* the
# PKCE verifier instead of a random handle into a server-side store. This keeps
# the login handshake completely stateless: it works across multiple uvicorn
# workers and survives a process restart (no more "Unknown or expired login
# state" when the callback lands on a different worker than the one that started
# the login).
_OAUTH_STATE_TYPE = "oauth_state"


def create_oauth_state(*, secret: str, verifier: str, ttl_minutes: int = 30) -> str:
    """Mint a signed OAuth ``state`` that embeds the PKCE code verifier."""
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, object] = {
        "typ": _OAUTH_STATE_TYPE,
        "vfr": verifier,
        # A nonce keeps two logins started in the same second distinguishable.
        "nonce": secrets.token_urlsafe(9),
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": "voidswitch",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_oauth_state(state: str, *, secret: str) -> str:
    """Recover the PKCE verifier from a signed OAuth ``state``.

    Raises ``jwt.PyJWTError`` when the state is missing, tampered with, expired,
    or not an OAuth-state token.
    """
    claims = jwt.decode(
        state,
        secret,
        algorithms=["HS256"],
        issuer="voidswitch",
        options={"require": ["exp", "iat"]},
    )
    if claims.get("typ") != _OAUTH_STATE_TYPE:
        raise jwt.InvalidTokenError("not an OAuth state token")
    verifier = claims.get("vfr")
    if not isinstance(verifier, str) or not verifier:
        raise jwt.InvalidTokenError("OAuth state missing PKCE verifier")
    return verifier


def _fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, secret: str) -> str:
    """Encrypt a provider API key at rest with a key derived from the app secret."""
    return _fernet(secret).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, *, secret: str) -> str:
    """Decrypt a value produced by :func:`encrypt_secret`.

    Falls back to treating the value as plaintext if it was never encrypted
    (tolerates manual DB seeding / migrations from an unencrypted store).
    """
    try:
        return _fernet(secret).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ciphertext
