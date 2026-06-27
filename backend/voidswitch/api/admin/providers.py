"""Admin: provider CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeySelectMode, KeyStatus, ProxyMode
from voidswitch.core.audit import AuditAction, record_audit, split_sensitive
from voidswitch.core.auth import (
    actor_display_name,
    audit_scope_for,
    get_current_user,
    is_owner,
    is_staff,
    require_owner,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger
from voidswitch.core.security import (
    decrypt_secret,
    encrypt_secret,
    generate_provider_api_token,
    hash_token,
)
from voidswitch.models.db import Provider, Proxy, User
from voidswitch.models.schemas import (
    ProviderCreate,
    ProviderKeyApiOut,
    ProviderKeyApiSecret,
    ProviderOut,
    ProviderUpdate,
)
from voidswitch.services.providers.registry import (
    adapter_catalog,
    adapter_class,
    get_adapter,
)

log = get_logger("admin.providers")

router = APIRouter(prefix="/api/admin/providers", tags=["admin:providers"])

_PROXY_MODES = {m.value for m in ProxyMode}
_KEY_SELECT_MODES = {m.value for m in KeySelectMode}


def _validate_key_select_mode(mode: str | None) -> None:
    if mode is not None and mode not in _KEY_SELECT_MODES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"key_select_mode must be one of {sorted(_KEY_SELECT_MODES)}.",
        )


def _to_out(
    provider: Provider, *, redact: bool = False, show_key_api: bool = False
) -> ProviderOut:
    out = ProviderOut.model_validate(provider)
    out.key_count = len(provider.keys)
    out.active_key_count = sum(1 for k in provider.keys if k.status == KeyStatus.ACTIVE.value)
    out.supports_balance = get_adapter(provider).balance_url is not None
    if redact:
        # Members may view providers (to add keys) but must not see potentially
        # secret config such as custom auth headers.
        out.extra_headers = dict.fromkeys(out.extra_headers, "***")
    if not show_key_api:
        # The key-management API credential is an owner / co-owner concern only.
        out.key_api_enabled = False
        out.key_api_token_preview = None
    return out


def _token_preview(raw: str) -> str:
    """Short, non-secret label for a key-management token (column is 48 chars)."""
    return f"{raw[:8]}…{raw[-4:]}" if len(raw) > 14 else raw[:4] + "***"


def _ensure_can_edit(user: User, provider: Provider) -> None:
    """Staff edit any provider; members only the ones they added."""
    if is_staff(user) or provider.added_by == user.id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You can only modify providers you added."
    )


async def _validate_proxy_config(
    session: AsyncSession, mode: str | None, proxy_ids: list[int] | None
) -> None:
    """Reject an unknown proxy_mode or proxy_ids that don't reference real proxies."""
    if mode is not None and mode not in _PROXY_MODES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"proxy_mode must be one of {sorted(_PROXY_MODES)}.",
        )
    if proxy_ids:
        found = (
            (await session.execute(select(Proxy.id).where(Proxy.id.in_(proxy_ids)))).scalars().all()
        )
        missing = sorted(set(proxy_ids) - set(found))
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown proxy id(s): {missing}."
            )


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ProviderOut]:
    rows = (
        (await session.execute(select(Provider).order_by(Provider.priority, Provider.id)))
        .scalars()
        .all()
    )
    redact = not is_staff(user)
    show_key_api = is_owner(user)
    return [_to_out(p, redact=redact, show_key_api=show_key_api) for p in rows]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ProviderOut:
    existing = (
        await session.execute(select(Provider).where(Provider.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider name already exists.")

    cls = adapter_class(body.type)
    models = body.models or list(cls.default_models)
    base_url = body.base_url or cls.default_base_url
    await _validate_proxy_config(session, body.proxy_mode, body.proxy_ids)
    _validate_key_select_mode(body.key_select_mode)

    provider = Provider(
        name=body.name,
        type=body.type,
        base_url=base_url,
        enabled=body.enabled,
        priority=body.priority,
        weight=body.weight,
        models=models,
        model_map=body.model_map,
        balance_url=body.balance_url,
        extra_headers=body.extra_headers,
        timeout_seconds=body.timeout_seconds,
        drop_opencode_identity_block=body.drop_opencode_identity_block,
        proxy_mode=body.proxy_mode,
        proxy_ids=body.proxy_ids,
        key_select_mode=body.key_select_mode,
        model_routes=[r.model_dump() for r in body.model_routes],
        added_by=user.id,
        added_by_name=actor_display_name(user),
    )
    session.add(provider)
    await session.flush()
    # Custom auth headers can hold upstream secrets — keep them owner-only.
    sensitive = {"extra_headers": provider.extra_headers} if provider.extra_headers else None
    await record_audit(
        session,
        action=AuditAction.PROVIDER_CREATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="provider",
        target_id=provider.id,
        detail={
            "name": provider.name,
            "type": provider.type,
            "base_url": provider.base_url,
        },
        sensitive=sensitive,
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=audit_scope_for(user),
    )
    await session.refresh(provider)
    return _to_out(provider, show_key_api=is_owner(user))


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ProviderOut:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    _ensure_can_edit(user, provider)
    changes = body.model_dump(exclude_unset=True)
    # Filter out fields where the value didn't actually change.
    real_changes: dict = {}
    for field, value in changes.items():
        old = getattr(provider, field, None)
        if old != value:
            real_changes[field] = value
    if not real_changes:
        await session.refresh(provider)
        return _to_out(provider, show_key_api=is_owner(user))
    # Allow renaming a provider after creation, but keep names unique.
    if "name" in real_changes and real_changes["name"] != provider.name:
        clash = (
            await session.execute(
                select(Provider.id).where(
                    Provider.name == real_changes["name"], Provider.id != provider_id
                )
            )
        ).first()
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Provider name already exists.")
    if "proxy_mode" in real_changes or "proxy_ids" in real_changes:
        await _validate_proxy_config(
            session,
            real_changes.get("proxy_mode", provider.proxy_mode),
            real_changes.get("proxy_ids", provider.proxy_ids),
        )
    if "key_select_mode" in real_changes:
        _validate_key_select_mode(real_changes["key_select_mode"])
    for field, value in real_changes.items():
        setattr(provider, field, value)
    await session.flush()
    # Record the actual changed values; divert any secret auth headers to the
    # owner-only sensitive blob so they never show in the plain detail.
    public_changes, sensitive = split_sensitive(real_changes, {"extra_headers"})
    await record_audit(
        session,
        action=AuditAction.PROVIDER_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="provider",
        target_id=provider.id,
        detail={"name": provider.name, "changes": public_changes},
        sensitive=sensitive,
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=audit_scope_for(user),
    )
    await session.refresh(provider)
    return _to_out(provider, show_key_api=is_owner(user))


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_owner),
) -> None:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    await session.delete(provider)
    await record_audit(
        session,
        action=AuditAction.PROVIDER_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="provider",
        target_id=provider_id,
        detail={"name": provider.name, "type": provider.type},
        ip=request.client.host if request.client else None,
    )


# --------------------------------------------------------------------------- #
# Per-provider key-management API credential (owner / co-owner only)
# --------------------------------------------------------------------------- #


async def _get_provider_or_404(session: AsyncSession, provider_id: int) -> Provider:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    return provider


def _key_api_status(provider: Provider) -> ProviderKeyApiOut:
    return ProviderKeyApiOut(
        provider_id=provider.id,
        provider_uuid=provider.uuid,
        enabled=provider.key_api_enabled,
        token_preview=provider.key_api_token_preview,
    )


@router.get("/{provider_id}/key-api", response_model=ProviderKeyApiOut)
async def get_key_api(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_owner),
) -> ProviderKeyApiOut:
    """Owner-only: current key-management API state for a provider."""
    provider = await _get_provider_or_404(session, provider_id)
    return _key_api_status(provider)


async def _mint_key_api(
    provider: Provider, session: AsyncSession, *, actor: User, request: Request, action: str
) -> ProviderKeyApiSecret:
    settings = get_settings()
    raw = generate_provider_api_token()
    provider.key_api_enabled = True
    provider.key_api_token_hash = hash_token(raw)
    provider.key_api_token_ciphertext = encrypt_secret(raw, secret=settings.server.secret_key)
    provider.key_api_token_preview = _token_preview(raw)
    await session.flush()
    await record_audit(
        session,
        action=action,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="provider",
        target_id=provider.id,
        detail={"name": provider.name},
        sensitive={"key_api_token": raw},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
    )
    return ProviderKeyApiSecret(
        provider_id=provider.id,
        provider_uuid=provider.uuid,
        enabled=True,
        token_preview=provider.key_api_token_preview,
        token=raw,
    )


@router.post("/{provider_id}/key-api/enable", response_model=ProviderKeyApiSecret)
async def enable_key_api(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> ProviderKeyApiSecret:
    """Owner-only: enable the key-management API and mint its token (shown once).

    Idempotent on the "enabled" flag, but a fresh token is generated each call —
    use it to (re)issue a credential. Existing enabled providers should prefer
    ``/rotate`` for clarity.
    """
    provider = await _get_provider_or_404(session, provider_id)
    return await _mint_key_api(
        provider, session, actor=actor, request=request,
        action=AuditAction.PROVIDER_KEY_API_ENABLE.value,
    )


@router.post("/{provider_id}/key-api/rotate", response_model=ProviderKeyApiSecret)
async def rotate_key_api(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> ProviderKeyApiSecret:
    """Owner-only: generate a new token, invalidating the previous one."""
    provider = await _get_provider_or_404(session, provider_id)
    return await _mint_key_api(
        provider, session, actor=actor, request=request,
        action=AuditAction.PROVIDER_KEY_API_ROTATE.value,
    )


@router.post("/{provider_id}/key-api/disable", response_model=ProviderKeyApiOut)
async def disable_key_api(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> ProviderKeyApiOut:
    """Owner-only: disable the key-management API and revoke its token."""
    provider = await _get_provider_or_404(session, provider_id)
    provider.key_api_enabled = False
    provider.key_api_token_hash = None
    provider.key_api_token_ciphertext = None
    provider.key_api_token_preview = None
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROVIDER_KEY_API_DISABLE,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="provider",
        target_id=provider.id,
        detail={"name": provider.name},
        ip=request.client.host if request.client else None,
    )
    return _key_api_status(provider)


@router.post("/{provider_id}/key-api/reveal", response_model=ProviderKeyApiSecret)
async def reveal_key_api(
    provider_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> ProviderKeyApiSecret:
    """Owner-only: reveal the current key-management token's plaintext. Audited."""
    provider = await _get_provider_or_404(session, provider_id)
    if not provider.key_api_enabled or not provider.key_api_token_ciphertext:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Key-management API is not enabled for this provider.",
        )
    settings = get_settings()
    raw = decrypt_secret(provider.key_api_token_ciphertext, secret=settings.server.secret_key)
    await record_audit(
        session,
        action=AuditAction.PROVIDER_KEY_API_REVEAL,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="provider",
        target_id=provider.id,
        detail={"name": provider.name, "token_preview": provider.key_api_token_preview},
        ip=request.client.host if request.client else None,
    )
    return ProviderKeyApiSecret(
        provider_id=provider.id,
        provider_uuid=provider.uuid,
        enabled=True,
        token_preview=provider.key_api_token_preview,
        token=raw,
    )


@router.get("/catalog/types")
async def provider_catalog(_: User = Depends(get_current_user)) -> list[dict[str, object]]:
    return adapter_catalog()


class FetchModelsRequest(BaseModel):
    base_url: str
    token: str
    method: str = "GET"
    path: str = "/models"


@router.post("/fetch-models")
async def fetch_provider_models(
    body: FetchModelsRequest,
    _: User = Depends(get_current_user),
) -> dict:
    """Proxy a GET/POST call to a provider's model-listing endpoint.

    Avoids CORS when the admin dashboard tries to call the provider API directly.
    """
    base = body.base_url.rstrip("/")
    path = body.path.strip()
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    elif "/.." in path or path.startswith(".."):
        parts = base.split("/")
        for seg in path.split("/"):
            if seg == "..":
                if len(parts) > 3:
                    parts.pop()
            else:
                parts.append(seg)
        url = "/".join(parts)
    else:
        url = f"{base}/{path.lstrip('/')}"
    method = body.method.upper()
    if method not in ("GET", "POST"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "method must be GET or POST")
    log.info("fetch_models_start", url=url, method=method)

    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0),
            follow_redirects=True,
        ) as client:
            kw = {"headers": {"Authorization": f"Bearer {body.token}"}}
            if method == "GET":
                r = await client.get(url, **kw)
            else:
                r = await client.post(url, **kw)
    except httpx.TimeoutException as exc:
        log.error("fetch_models_timeout", url=url, error=str(exc))
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            f"Provider timed out ({exc}). Check network connectivity to {url}.",
        ) from exc
    except Exception as exc:
        log.exception("fetch_models_connection_error", url=url)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not reach provider: {exc}",
        ) from exc

    ct = r.headers.get("content-type", "")
    log.info("fetch_models_response", url=url, status=r.status_code, content_type=ct)

    if r.status_code >= 400:
        detail = r.text[:1024]
        log.warning("fetch_models_upstream_error", url=url, status=r.status_code, body=detail)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Provider returned {r.status_code}: {detail}",
        )

    try:
        data = r.json()
    except Exception as exc:
        log.warning("fetch_models_non_json", url=url, body=r.text[:512])
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Provider returned non-JSON response ({exc}). Body preview: {r.text[:256]}",
        ) from exc

    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", data.get("models", data.get("result", [])))

    if not isinstance(items, list):
        log.warning("fetch_models_bad_format", url=url, data=str(data)[:512])
        keys = list(data.keys()) if isinstance(data, dict) else "not an object"
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Unexpected response format. Keys: {keys}. Body: {str(data)[:256]}",
        )

    model_ids: list[str] = []
    for m in items:
        if isinstance(m, str):
            model_ids.append(m)
        elif isinstance(m, dict):
            mid = m.get("id") or m.get("name") or ""
            if mid:
                model_ids.append(str(mid))

    log.info("fetch_models_ok", url=url, count=len(model_ids))
    return {"models": model_ids}
