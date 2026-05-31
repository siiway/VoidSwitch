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


def generate_void_token() -> str:
    """A high-entropy client-facing token. Prefixed for easy identification."""
    return f"{VOID_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


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
