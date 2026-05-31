"""Admin: upstream API key pool management (batch add, status, delete).

Also hosts the Claude Code subscription OAuth login (``/oauth/start`` +
``/oauth/complete``) for ``claude-code`` providers, which mints a credential
bundle and stores it as a provider key.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus
from voidswitch.core.audit import record_audit
from voidswitch.core.auth import require_staff
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider, User
from voidswitch.models.schemas import (
    ApiKeyCreate,
    ApiKeyOut,
    ApiKeyUpdate,
    ClaudeOAuthComplete,
    ClaudeOAuthStart,
)
from voidswitch.services import oauth_tokens

router = APIRouter(prefix="/api/admin/providers/{provider_id}/keys", tags=["admin:keys"])


def _preview(raw: str) -> str:
    raw = raw.strip()
    if len(raw) <= 10:
        return raw[:2] + "***"
    return f"{raw[:4]}…{raw[-4:]}"


def _oauth_preview(bundle: dict[str, object]) -> str:
    """A short, non-secret label for an OAuth key (column is 32 chars)."""
    return f"oauth·{_preview(str(bundle.get('access_token', '')))}"[:32]


async def _get_provider(session: AsyncSession, provider_id: int) -> Provider:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    return provider


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[ApiKey]:
    await _get_provider(session, provider_id)
    rows = (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.provider_id == provider_id).order_by(ApiKey.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("", response_model=list[ApiKeyOut], status_code=status.HTTP_201_CREATED)
async def add_keys(
    provider_id: int,
    body: ApiKeyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> list[ApiKey]:
    await _get_provider(session, provider_id)

    # De-dupe within the batch and against existing rows for this provider.
    existing_hashes = {
        h
        for (h,) in (
            await session.execute(select(ApiKey.key_hash).where(ApiKey.provider_id == provider_id))
        ).all()
    }
    created: list[ApiKey] = []
    seen: set[str] = set()
    for raw in body.keys:
        raw = raw.strip()
        if not raw:
            continue
        digest = hash_token(raw)
        if digest in existing_hashes or digest in seen:
            continue
        seen.add(digest)
        key = ApiKey(
            provider_id=provider_id,
            key_ciphertext=encrypt_secret(raw, secret=settings.server.secret_key),
            key_hash=digest,
            key_preview=_preview(raw),
            status=KeyStatus.ACTIVE.value,
            weight=body.weight,
            note=body.note,
        )
        session.add(key)
        created.append(key)

    if not created:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No new keys to add.")

    await session.flush()
    await record_audit(
        session,
        action="key.add",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider_id,
        detail={"added": len(created)},
        ip=request.client.host if request.client else None,
    )
    return created


# --------------------------------------------------------------------------- #
# Claude Code subscription OAuth login (claude-code providers only)
# --------------------------------------------------------------------------- #


def _require_claude_code(provider: Provider) -> None:
    if provider.type != "claude-code":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "OAuth login is only available for claude-code providers.",
        )


@router.post("/oauth/start", response_model=ClaudeOAuthStart)
async def oauth_start(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ClaudeOAuthStart:
    """Begin a Claude subscription OAuth login: return the authorize URL + state."""
    provider = await _get_provider(session, provider_id)
    _require_claude_code(provider)
    authorize_url, state = oauth_tokens.begin_login(provider_id)
    await record_audit(
        session,
        action="key.oauth_start",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider_id,
        ip=request.client.host if request.client else None,
    )
    return ClaudeOAuthStart(authorize_url=authorize_url, state=state)


@router.post("/oauth/complete", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
async def oauth_complete(
    provider_id: int,
    body: ClaudeOAuthComplete,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    """Exchange the pasted code for a credential bundle and store it as a key."""
    provider = await _get_provider(session, provider_id)
    _require_claude_code(provider)
    try:
        bundle = await oauth_tokens.complete_login(
            body.code, body.state, provider_id=provider_id, session=session
        )
    except oauth_tokens.LoginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except oauth_tokens.LoginUpstreamError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    # Each successful login mints a distinct credential (the access/refresh
    # tokens and expiry rotate every time), so there is no stable identity to
    # dedupe on — we always insert a fresh key. A superseded key keeps working
    # until its token expires, then self-disables when a refresh 401s.
    plaintext = json.dumps(bundle)
    key = ApiKey(
        provider_id=provider_id,
        key_ciphertext=encrypt_secret(plaintext, secret=settings.server.secret_key),
        key_hash=hash_token(plaintext),
        key_preview=_oauth_preview(bundle),
        status=KeyStatus.ACTIVE.value,
        note=body.note or "Claude subscription (OAuth)",
    )
    session.add(key)
    await session.flush()
    await record_audit(
        session,
        action="key.oauth_add",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider_id,
        detail={"key_id": key.id, "scopes": bundle.get("scopes", [])},
        ip=request.client.host if request.client else None,
    )
    return key


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_key(
    provider_id: int,
    key_id: int,
    body: ApiKeyUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None or key.provider_id != provider_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found.")
    if body.enabled is not None:
        key.status = KeyStatus.ACTIVE.value if body.enabled else KeyStatus.DISABLED.value
        if body.enabled:
            key.failed_count = 0
            key.disabled_reason = None
    if body.status is not None:
        key.status = body.status
        if body.status == KeyStatus.ACTIVE.value:
            key.failed_count = 0
            key.disabled_reason = None
    if body.weight is not None:
        key.weight = body.weight
    if body.note is not None:
        key.note = body.note
    await session.flush()
    return key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    provider_id: int,
    key_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.provider_id != provider_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found.")
    await session.delete(key)
