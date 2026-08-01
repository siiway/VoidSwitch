"""Admin: upstream API key pool management (batch add, status, delete).

The core key-lifecycle logic lives in :mod:`voidswitch.services.keymgmt` so it is
shared verbatim with the mounted per-provider key-management API. This module is
the dashboard-facing surface: it adapts the signed-in user into a
``keymgmt.Actor`` and keeps the Claude Code subscription OAuth login
(``/oauth/start`` + ``/oauth/complete``), which mints a credential bundle and
stores it as a provider key.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus
from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    is_staff,
    require_owner,
    require_staff,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import decrypt_secret, encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider, User
from voidswitch.models.schemas import (
    ApiKeyCleanup,
    ApiKeyCleanupResult,
    ApiKeyCreate,
    ApiKeyOut,
    ApiKeyReorder,
    ApiKeyUpdate,
    AuthImportRequest,
    AuthImportResult,
    ClaudeOAuthComplete,
    ClaudeOAuthStart,
)
from voidswitch.services import auth_import, keymgmt, oauth_tokens, xai_oauth

router = APIRouter(prefix="/api/admin/providers/{provider_id}/keys", tags=["admin:keys"])


def _actor(user: User, request: Request) -> keymgmt.Actor:
    return keymgmt.Actor(
        sub=user.sub,
        name=actor_display_name(user),
        user_id=user.id,
        is_staff=is_staff(user),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def _get_provider(session: AsyncSession, provider_id: int) -> Provider:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    return provider


async def _get_key(session: AsyncSession, provider_id: int, key_id: int) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None or key.provider_id != provider_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found.")
    return key


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[ApiKey]:
    provider = await _get_provider(session, provider_id)
    return await keymgmt.list_keys(session, provider, _actor(user, request))


@router.post("", response_model=list[ApiKeyOut], status_code=status.HTTP_201_CREATED)
async def add_keys(
    provider_id: int,
    body: ApiKeyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> list[ApiKey]:
    provider = await _get_provider(session, provider_id)
    return await keymgmt.add_keys(
        session, provider, body, actor=_actor(user, request), settings=settings
    )


@router.post("/import", response_model=AuthImportResult, status_code=status.HTTP_201_CREATED)
async def import_auth_files(
    provider_id: int,
    body: AuthImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> AuthImportResult:
    """Import credentials from sub2api / CLIProxyAPI (cpa) auth files.

    Accepts the raw text of one or more auth files (uploaded or pasted), parses
    every account they carry, and stores each as a key on this provider. OAuth
    accounts become credential bundles; api-key/cookie accounts store their raw
    secret. Only Claude OAuth bundles are auto-refreshed by VoidSwitch.
    """
    provider = await _get_provider(session, provider_id)
    if not body.sources or not any(s.strip() for s in body.sources):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No auth file content provided.")
    result = await auth_import.import_credentials(
        session,
        provider,
        sources=body.sources,
        pool=body.pool,
        note=body.note,
        actor=_actor(user, request),
        settings=settings,
    )
    if result.imported == 0 and result.duplicates == 0 and result.unusable == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No credentials were found in the provided files.",
        )
    return result


@router.post("/refresh-balance", response_model=list[ApiKeyOut])
async def refresh_balances(
    provider_id: int,
    request: Request,
    pool: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> list[ApiKey]:
    """Rescan balances for this provider's keys (optionally one ``pool`` only)."""
    provider = await _get_provider(session, provider_id)
    return await keymgmt.refresh_balances(
        session, provider, pool=pool, actor=_actor(user, request), settings=settings
    )


@router.post("/{key_id}/refresh-balance", response_model=ApiKeyOut)
async def refresh_balance_one(
    provider_id: int,
    key_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    """Refresh a single key's balance on demand."""
    provider = await _get_provider(session, provider_id)
    key = await _get_key(session, provider_id, key_id)
    return await keymgmt.refresh_balance_one(
        session, provider, key, actor=_actor(user, request), settings=settings
    )


@router.post("/{key_id}/refresh-token", response_model=ApiKeyOut)
async def refresh_token_one(
    provider_id: int,
    key_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    """Force-refresh a single key's OAuth access token (Claude Code / xAI).

    Immediately exchanges the stored refresh token for a fresh access token,
    re-encrypts the rotated bundle, and brings the key back online. The
    token-endpoint call lands in the request log stamped with the operator, and
    the action is written to the audit trail with the same attribution.
    """
    provider = await _get_provider(session, provider_id)
    key = await _get_key(session, provider_id, key_id)
    return await keymgmt.refresh_token_one(
        session, provider, key, actor=_actor(user, request), settings=settings
    )


@router.post("/reorder", response_model=list[ApiKeyOut])
async def reorder_keys(
    provider_id: int,
    body: ApiKeyReorder,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[ApiKey]:
    """Persist a new drag-sorted order for this provider's keys (staff only)."""
    provider = await _get_provider(session, provider_id)
    return await keymgmt.reorder_keys(session, provider, body, actor=_actor(user, request))


@router.post("/cleanup", response_model=ApiKeyCleanupResult)
async def cleanup_keys(
    provider_id: int,
    body: ApiKeyCleanup,
    request: Request,
    pool: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> ApiKeyCleanupResult:
    """Delete keys stuck in a dead state: ``invalid`` or ``insufficient_balance``."""
    provider = await _get_provider(session, provider_id)
    deleted = await keymgmt.cleanup_keys(
        session, provider, body, pool=pool, actor=_actor(user, request), settings=settings
    )
    return ApiKeyCleanupResult(deleted=deleted)


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_key(
    provider_id: int,
    key_id: int,
    body: ApiKeyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    provider = await _get_provider(session, provider_id)
    key = await _get_key(session, provider_id, key_id)
    return await keymgmt.update_key(
        session, provider, key, body, actor=_actor(user, request), settings=settings
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    provider_id: int,
    key_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
    settings: Settings = Depends(get_settings),
) -> None:
    provider = await _get_provider(session, provider_id)
    key = await _get_key(session, provider_id, key_id)
    await keymgmt.delete_key(
        session, provider, key, actor=_actor(user, request), settings=settings
    )


# --------------------------------------------------------------------------- #
# Subscription OAuth login (claude-code + grok-build providers)
# --------------------------------------------------------------------------- #

# Each entry maps a provider type to the service module that implements the
# manual redirect-paste OAuth flow (begin_login / complete_login / parse_bundle
# + LoginError / LoginUpstreamError). Both modules share the same public shape.
_OAUTH_MODULES = {
    "claude-code": oauth_tokens,
    "grok-build": xai_oauth,
}

_OAUTH_DEFAULT_NOTE = {
    "claude-code": "Claude subscription (OAuth)",
    "grok-build": "Grok Build (OAuth)",
}


def _oauth_module(provider: Provider):
    module = _OAUTH_MODULES.get(provider.type)
    if module is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "OAuth login is not available for this provider.",
        )
    return module


@router.post("/oauth/start", response_model=ClaudeOAuthStart)
async def oauth_start(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ClaudeOAuthStart:
    """Begin a subscription OAuth login: return the authorize URL + state."""
    provider = await _get_provider(session, provider_id)
    module = _oauth_module(provider)
    authorize_url, state = module.begin_login(provider_id)
    await record_audit(
        session,
        action=AuditAction.KEY_OAUTH_START,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="provider",
        target_id=provider_id,
        detail={"provider_name": provider.name},
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
    module = _oauth_module(provider)
    try:
        bundle = await module.complete_login(
            body.code, body.state, provider_id=provider_id, session=session
        )
    except module.LoginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except module.LoginUpstreamError as exc:
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
        key_preview=keymgmt.oauth_preview(bundle),
        status=KeyStatus.ACTIVE.value,
        note=body.note or _OAUTH_DEFAULT_NOTE.get(provider.type, "Subscription (OAuth)"),
        added_by=user.id,
        added_by_name=actor_display_name(user),
    )
    session.add(key)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.KEY_OAUTH_ADD,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="provider",
        target_id=provider_id,
        detail={
            "provider_name": provider.name,
            "key_id": key.id,
            "preview": key.key_preview,
            "scopes": bundle.get("scopes", []),
        },
        sensitive={"keys": [{"key": plaintext, "preview": keymgmt.oauth_preview(bundle)}]},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
    )
    return key


@router.post("/{key_id}/reveal")
async def reveal_key(
    provider_id: int,
    key_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Owner-only: decrypt and return an existing provider key's plaintext.

    Guarded behind a secondary confirmation in the UI; every reveal is audited.
    """
    key = await _get_key(session, provider_id, key_id)
    plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
    await record_audit(
        session,
        action=AuditAction.KEY_REVEAL,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="provider",
        target_id=provider_id,
        detail={"key_id": key.id, "preview": key.key_preview},
        ip=request.client.host if request.client else None,
    )
    result: dict[str, object] = {
        "id": key.id,
        "preview": key.key_preview,
        "key": plaintext,
        "is_bundle": False,
    }
    bundle = oauth_tokens.parse_bundle(plaintext)
    if bundle is not None:
        result["is_bundle"] = True
        result["access_token"] = bundle.get("access_token", "")
        result["refresh_token"] = bundle.get("refresh_token", "")
        result["expires_at"] = bundle.get("expires_at")
    return result
