"""Shared upstream-key management operations.

These actor-agnostic helpers implement the full lifecycle of a provider's
upstream API keys — list, add, edit, delete, balance refresh, and bulk cleanup.
They are used by two surfaces:

* the dashboard admin API (``/api/admin/providers/{id}/keys``), where the actor
  is the signed-in user, and
* the mounted per-provider **key-management API** sub-app, where the actor is the
  provider's own key-management token.

Keeping the logic here means both surfaces behave identically.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus
from voidswitch.core.audit import record_audit
from voidswitch.core.config import Settings
from voidswitch.core.security import decrypt_secret, encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider
from voidswitch.models.schemas import ApiKeyCleanup, ApiKeyCreate, ApiKeyUpdate
from voidswitch.services import oauth_tokens, settings_store
from voidswitch.services.balance import refresh_key_balance
from voidswitch.services.network import Route, get_pool
from voidswitch.services.providers.registry import get_adapter

CLEANUP_TARGETS = {KeyStatus.INVALID.value, KeyStatus.INSUFFICIENT_BALANCE.value}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(slots=True)
class Actor:
    """Who is performing a key operation, for scoping + audit attribution.

    * ``is_staff`` — when False the actor only sees/manages keys they personally
      added (``added_by == user_id``). The provider key-management token is
      treated as staff over *its own* provider, so it gets full access there.
    * ``user_id`` — populates ``ApiKey.added_by`` on new keys (None for the
      token-based API).
    """

    sub: str | None = None
    name: str | None = None
    user_id: int | None = None
    is_staff: bool = True
    ip: str | None = None


def preview(raw: str) -> str:
    raw = raw.strip()
    if len(raw) <= 10:
        return raw[:2] + "***"
    return f"{raw[:4]}…{raw[-4:]}"


def parse_key_line(line: str) -> tuple[str, str | None]:
    """Split an inbound key line into its secret and an optional ``# comment``."""
    secret, sep, comment = line.partition("#")
    comment = comment.strip()
    return secret.strip(), (comment if sep and comment else None)


def oauth_preview(bundle: dict[str, object]) -> str:
    """A short, non-secret label for an OAuth key (column is 48 chars)."""
    return f"oauth·{preview(str(bundle.get('access_token', '')))}"[:48]


def ensure_can_manage_key(actor: Actor, key: ApiKey) -> None:
    """Staff manage any key; members only the ones they added."""
    if actor.is_staff or key.added_by == actor.user_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only modify keys you added.")


async def list_keys(session: AsyncSession, provider: Provider, actor: Actor) -> list[ApiKey]:
    stmt = select(ApiKey).where(ApiKey.provider_id == provider.id)
    if not actor.is_staff:
        stmt = stmt.where(ApiKey.added_by == actor.user_id)
    rows = (await session.execute(stmt.order_by(ApiKey.id))).scalars().all()
    return list(rows)


async def add_keys(
    session: AsyncSession,
    provider: Provider,
    body: ApiKeyCreate,
    *,
    actor: Actor,
    settings: Settings,
) -> list[ApiKey]:
    """Batch-add keys (de-duped within the batch and against existing rows)."""
    is_claude_code = provider.type == "claude-code"
    existing_hashes = {
        h
        for (h,) in (
            await session.execute(
                select(ApiKey.key_hash).where(ApiKey.provider_id == provider.id)
            )
        ).all()
    }
    created: list[ApiKey] = []
    seen: set[str] = set()
    sensitive_keys: list[dict[str, str | None]] = []
    for line in body.keys:
        raw, comment = parse_key_line(line)
        if not raw:
            continue
        # For Claude Code providers, accept colon-separated OAuth bundles:
        # access_token:refresh_token:expires_at → JSON bundle.
        if is_claude_code and raw.count(":") == 2 and oauth_tokens.parse_bundle(raw) is None:
            parts = raw.split(":", 2)
            raw = json.dumps({
                "access_token": parts[0],
                "refresh_token": parts[1],
                "expires_at": float(parts[2]),
            })
        digest = hash_token(raw)
        if digest in existing_hashes or digest in seen:
            continue
        seen.add(digest)
        parsed = oauth_tokens.parse_bundle(raw)
        prev = oauth_preview(parsed) if is_claude_code and parsed is not None else preview(raw)
        sensitive_keys.append(
            {
                "key": raw,
                "preview": prev,
                "note": comment or body.note,
                "pool": body.pool or "",
            }
        )
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret(raw, secret=settings.server.secret_key),
            key_hash=digest,
            key_preview=prev,
            status=KeyStatus.ACTIVE.value,
            weight=body.weight,
            note=comment or body.note,
            pool=body.pool or "",
            added_by=actor.user_id,
            added_by_name=actor.name,
        )
        session.add(key)
        created.append(key)

    if not created:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No new keys to add.")

    await session.flush()
    await record_audit(
        session,
        action="key.add",
        actor_sub=actor.sub,
        actor_name=actor.name,
        target_type="provider",
        target_id=provider.id,
        detail={"added": len(created)},
        sensitive={"keys": sensitive_keys},
        secret_key=settings.server.secret_key,
        ip=actor.ip,
    )
    return created


async def update_key(
    session: AsyncSession,
    provider: Provider,
    key: ApiKey,
    body: ApiKeyUpdate,
    *,
    actor: Actor,
    settings: Settings,
) -> ApiKey:
    ensure_can_manage_key(actor, key)

    has_bundle_update = (
        body.access_token is not None
        or body.refresh_token is not None
        or body.expires_at is not None
    )
    if has_bundle_update:
        if body.key is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot supply both a raw key and OAuth bundle fields simultaneously.",
            )
        if provider.type != "claude-code":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "OAuth bundle fields are only available for claude-code providers.",
            )
        plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
        bundle: dict = oauth_tokens.parse_bundle(plaintext) or {}
        if body.access_token is not None:
            bundle["access_token"] = body.access_token
        if body.refresh_token is not None:
            bundle["refresh_token"] = body.refresh_token
        if body.expires_at is not None:
            bundle["expires_at"] = body.expires_at
        if not bundle.get("access_token"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "access_token is required for an OAuth bundle."
            )
        raw = json.dumps(bundle)
        await _ensure_no_clash(session, provider.id, raw, key.id)
        key.key_ciphertext = encrypt_secret(raw, secret=settings.server.secret_key)
        key.key_hash = hash_token(raw)
        key.key_preview = oauth_preview(bundle)
        key.failed_count = 0
        key.disabled_reason = None
    elif body.key is not None:
        raw = body.key.strip()
        if not raw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Key cannot be empty.")
        await _ensure_no_clash(session, provider.id, raw, key.id)
        # A fresh secret invalidates prior failures tied to the old credential.
        key.key_ciphertext = encrypt_secret(raw, secret=settings.server.secret_key)
        key.key_hash = hash_token(raw)
        key.key_preview = preview(raw)
        key.failed_count = 0
        key.disabled_reason = None
    if body.enabled is not None:
        key.status = KeyStatus.ACTIVE.value if body.enabled else KeyStatus.DISABLED.value
        if body.enabled:
            key.failed_count = 0
            key.disabled_reason = None
            key.disabled_since = None
        elif key.disabled_since is None:
            key.disabled_since = _utcnow()
    if body.status is not None:
        key.status = body.status
        if body.status == KeyStatus.ACTIVE.value:
            key.failed_count = 0
            key.disabled_reason = None
            key.disabled_since = None
        elif key.disabled_since is None:
            key.disabled_since = _utcnow()
    if body.weight is not None:
        key.weight = body.weight
    if body.note is not None:
        key.note = body.note
    if body.pool is not None:
        key.pool = body.pool
    await session.flush()
    await record_audit(
        session,
        action="key.update",
        actor_sub=actor.sub,
        actor_name=actor.name,
        target_type="provider",
        target_id=provider.id,
        detail={"key_id": key.id, "changes": list(body.model_dump(exclude_unset=True))},
        ip=actor.ip,
    )
    return key


async def _ensure_no_clash(
    session: AsyncSession, provider_id: int, raw: str, key_id: int
) -> None:
    digest = hash_token(raw)
    clash = (
        await session.execute(
            select(ApiKey.id).where(
                ApiKey.provider_id == provider_id,
                ApiKey.key_hash == digest,
                ApiKey.id != key_id,
            )
        )
    ).first()
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another key with this value already exists."
        )


async def delete_key(
    session: AsyncSession,
    provider: Provider,
    key: ApiKey,
    *,
    actor: Actor,
    settings: Settings,
) -> None:
    ensure_can_manage_key(actor, key)
    # Capture the full (decrypted) key so an owner can recover/inspect it later.
    plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
    await record_audit(
        session,
        action="key.delete",
        actor_sub=actor.sub,
        actor_name=actor.name,
        target_type="provider",
        target_id=provider.id,
        detail={"key_id": key.id, "preview": key.key_preview, "pool": key.pool},
        sensitive={
            "keys": [
                {
                    "key": plaintext,
                    "preview": key.key_preview,
                    "note": key.note,
                    "pool": key.pool,
                    "added_by_name": key.added_by_name,
                }
            ]
        },
        secret_key=settings.server.secret_key,
        ip=actor.ip,
    )
    await session.delete(key)


# --------------------------------------------------------------------------- #
# Balance refresh
# --------------------------------------------------------------------------- #


async def refresh_one(key: ApiKey, provider: Provider, settings: Settings) -> bool | None:
    """Probe a single key's balance, applying auto enable/disable. Never raises."""
    auto_disable = settings_store.get_bool("auto_disable_zero_balance", True)
    pool = get_pool()
    client = await pool.get(Route(), connect_timeout=15.0, read_timeout=30.0)
    try:
        return await refresh_key_balance(
            key, provider, client, settings, auto_disable=auto_disable
        )
    except Exception:
        return None


def require_balance_support(provider: Provider) -> None:
    if get_adapter(provider).balance_url is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This provider does not support balance queries.",
        )


async def refresh_balances(
    session: AsyncSession,
    provider: Provider,
    *,
    pool: str | None,
    actor: Actor,
    settings: Settings,
) -> list[ApiKey]:
    """Rescan balances for a provider's keys (optionally a single ``pool``)."""
    require_balance_support(provider)
    stmt = select(ApiKey).where(ApiKey.provider_id == provider.id)
    if pool is not None:
        stmt = stmt.where(ApiKey.pool == pool)
    if not actor.is_staff:
        stmt = stmt.where(ApiKey.added_by == actor.user_id)
    keys = (await session.execute(stmt.order_by(ApiKey.id))).scalars().all()

    rate = settings_store.get_int("balance_scan_rate_per_second", 5)
    delay = 1.0 / rate if rate > 0 else 0.0
    for index, key in enumerate(keys):
        if delay and index:
            await asyncio.sleep(delay)
        await refresh_one(key, provider, settings)
    await session.flush()
    return list(keys)


async def refresh_balance_one(
    session: AsyncSession,
    provider: Provider,
    key: ApiKey,
    *,
    actor: Actor,
    settings: Settings,
) -> ApiKey:
    ensure_can_manage_key(actor, key)
    require_balance_support(provider)
    await refresh_one(key, provider, settings)
    await session.flush()
    return key


# --------------------------------------------------------------------------- #
# Bulk cleanup of dead keys (invalid / out-of-balance)
# --------------------------------------------------------------------------- #


async def cleanup_keys(
    session: AsyncSession,
    provider: Provider,
    body: ApiKeyCleanup,
    *,
    pool: str | None,
    actor: Actor,
    settings: Settings,
) -> int:
    """Delete keys stuck in a dead state: ``invalid`` or ``insufficient_balance``."""
    if body.target not in CLEANUP_TARGETS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"target must be one of {sorted(CLEANUP_TARGETS)}.",
        )
    stmt = select(ApiKey).where(
        ApiKey.provider_id == provider.id,
        ApiKey.status == body.target,
    )
    if pool is not None:
        stmt = stmt.where(ApiKey.pool == pool)
    if not actor.is_staff:
        stmt = stmt.where(ApiKey.added_by == actor.user_id)
    keys = (await session.execute(stmt)).scalars().all()

    cutoff: dt.datetime | None = None
    if body.target == KeyStatus.INSUFFICIENT_BALANCE.value and body.min_days > 0:
        cutoff = _utcnow() - dt.timedelta(days=body.min_days)

    doomed: list[ApiKey] = []
    for key in keys:
        if cutoff is not None:
            since = key.disabled_since
            # Without a recorded disable time we cannot prove the age — skip it.
            if since is None:
                continue
            if since.tzinfo is None:
                since = since.replace(tzinfo=dt.UTC)
            if since > cutoff:
                continue
        doomed.append(key)

    if not doomed:
        return 0

    ids = [k.id for k in doomed]
    await session.execute(delete(ApiKey).where(ApiKey.id.in_(ids)))
    await record_audit(
        session,
        action="key.cleanup",
        actor_sub=actor.sub,
        actor_name=actor.name,
        target_type="provider",
        target_id=provider.id,
        detail={"target": body.target, "min_days": body.min_days, "deleted": len(ids)},
        ip=actor.ip,
    )
    return len(ids)
