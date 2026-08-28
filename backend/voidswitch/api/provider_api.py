"""Mounted per-provider **key-management API** sub-application.

A standalone FastAPI app (its own OpenAPI schema + Swagger UI at
``/provider-api/docs``) that lets an external integration manage the upstream API
keys of a *single* provider, authenticated by that provider's key-management
token (``vsk-…``). The token is enabled, rotated, and revealed by (co-)owners
from the dashboard; see ``/api/admin/providers/{id}/key-api``.

Every request is scoped to exactly one provider — the one the presented token
belongs to — and reuses the same key-lifecycle logic as the admin dashboard
(:mod:`voidswitch.services.keymgmt`), so behaviour is identical.

Authenticate with either::

    Authorization: Bearer vsk-...
    X-API-Key: vsk-...
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch import __version__
from voidswitch.core.auth import _bearer
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import hash_token
from voidswitch.models.db import ApiKey, Provider
from voidswitch.models.schemas import (
    ApiKeyCleanup,
    ApiKeyCleanupResult,
    ApiKeyCreate,
    ApiKeyOut,
    ApiKeyReorder,
    ApiKeyUpdate,
    ProviderOut,
)
from voidswitch.services import keymgmt

subapp = FastAPI(
    title="VoidSwitch — Provider Key API",
    version=__version__,
    description=(
        "Manage one provider's upstream API keys with that provider's "
        "key-management token (`vsk-…`). Send it as `Authorization: Bearer …` "
        "or `X-API-Key: …`."
    ),
)


async def authed_provider(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Provider:
    """Resolve the provider a key-management token belongs to (or 401)."""
    raw = _bearer(authorization) or x_api_key
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing key-management token.")
    provider = (
        await session.execute(
            select(Provider).where(Provider.key_api_token_hash == hash_token(raw))
        )
    ).scalar_one_or_none()
    if provider is None or not provider.key_api_enabled or not provider.key_api_token_hash:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or disabled key-management token."
        )
    if not provider.enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "This provider is currently disabled. "
            "Enable it from the dashboard to use the key-management API.",
        )
    return provider


def _actor(provider: Provider, request: Request) -> keymgmt.Actor:
    # The token has full authority over its own provider's keys (is_staff=True),
    # but is not a user, so new keys carry no ``added_by`` id.
    return keymgmt.Actor(
        sub=f"provider-key-api:{provider.uuid}",
        name=f"key-api:{provider.name}",
        user_id=None,
        is_staff=True,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def _get_key(session: AsyncSession, provider: Provider, key_id: int) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None or key.provider_id != provider.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found.")
    return key


@subapp.get("/provider", response_model=ProviderOut, tags=["provider"])
async def whoami(provider: Provider = Depends(authed_provider)) -> ProviderOut:
    """Return the provider this token manages."""
    out = ProviderOut.model_validate(provider)
    out.key_count = len(provider.keys)
    out.active_key_count = sum(1 for k in provider.keys if k.status == "active")
    # Never echo the management-credential state back through the token API.
    out.key_api_enabled = False
    out.key_api_token_preview = None
    out.extra_headers = dict.fromkeys(out.extra_headers, "***")
    return out


@subapp.get("/keys", response_model=list[ApiKeyOut], tags=["keys"])
async def list_keys(
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKey]:
    """List this provider's upstream keys."""
    return await keymgmt.list_keys(session, provider, _actor(provider, request))


@subapp.post(
    "/keys", response_model=list[ApiKeyOut], status_code=status.HTTP_201_CREATED, tags=["keys"]
)
async def add_keys(
    body: ApiKeyCreate,
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ApiKey]:
    """Batch-add upstream keys (newline list; inline ``# comment`` per key)."""
    return await keymgmt.add_keys(
        session, provider, body, actor=_actor(provider, request), settings=settings
    )


@subapp.patch("/keys/{key_id}", response_model=ApiKeyOut, tags=["keys"])
async def update_key(
    key_id: int,
    body: ApiKeyUpdate,
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    """Edit a key: replace the secret, set the pool/note/weight, enable/disable."""
    key = await _get_key(session, provider, key_id)
    return await keymgmt.update_key(
        session, provider, key, body, actor=_actor(provider, request), settings=settings
    )


@subapp.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["keys"])
async def delete_key(
    key_id: int,
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete a key."""
    key = await _get_key(session, provider, key_id)
    await keymgmt.delete_key(
        session, provider, key, actor=_actor(provider, request), settings=settings
    )


@subapp.post("/keys/reorder", response_model=list[ApiKeyOut], tags=["keys"])
async def reorder_keys(
    body: ApiKeyReorder,
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKey]:
    """Persist a new drag-sorted order for this provider's keys."""
    return await keymgmt.reorder_keys(session, provider, body, actor=_actor(provider, request))


@subapp.post("/keys/refresh-balance", response_model=list[ApiKeyOut], tags=["batch"])
async def refresh_balances(
    request: Request,
    pool: str | None = None,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ApiKey]:
    """Rescan balances for all of this provider's keys (optionally one ``pool``)."""
    return await keymgmt.refresh_balances(
        session, provider, pool=pool, actor=_actor(provider, request), settings=settings
    )


@subapp.post("/keys/{key_id}/refresh-balance", response_model=ApiKeyOut, tags=["batch"])
async def refresh_balance_one(
    key_id: int,
    request: Request,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApiKey:
    """Refresh a single key's balance on demand."""
    key = await _get_key(session, provider, key_id)
    return await keymgmt.refresh_balance_one(
        session, provider, key, actor=_actor(provider, request), settings=settings
    )


@subapp.post("/keys/cleanup", response_model=ApiKeyCleanupResult, tags=["batch"])
async def cleanup_keys(
    body: ApiKeyCleanup,
    request: Request,
    pool: str | None = None,
    provider: Provider = Depends(authed_provider),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApiKeyCleanupResult:
    """Bulk-delete dead keys (``invalid`` / ``insufficient_balance``).

    For ``insufficient_balance``, ``min_days`` keeps keys disabled for fewer than
    that many days. An optional ``pool`` query param restricts the scope.
    """
    deleted = await keymgmt.cleanup_keys(
        session, provider, body, pool=pool, actor=_actor(provider, request), settings=settings
    )
    return ApiKeyCleanupResult(deleted=deleted)
