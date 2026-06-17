"""Admin: provider CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus, ProxyMode
from voidswitch.core.audit import record_audit
from voidswitch.core.auth import (
    actor_display_name,
    get_current_user,
    is_staff,
    require_owner,
)
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger
from voidswitch.models.db import Provider, Proxy, User
from voidswitch.models.schemas import ProviderCreate, ProviderOut, ProviderUpdate
from voidswitch.services.providers.registry import (
    adapter_catalog,
    adapter_class,
    get_adapter,
)

log = get_logger("admin.providers")

router = APIRouter(prefix="/api/admin/providers", tags=["admin:providers"])

_PROXY_MODES = {m.value for m in ProxyMode}


def _to_out(provider: Provider, *, redact: bool = False) -> ProviderOut:
    out = ProviderOut.model_validate(provider)
    out.key_count = len(provider.keys)
    out.active_key_count = sum(1 for k in provider.keys if k.status == KeyStatus.ACTIVE.value)
    out.supports_balance = get_adapter(provider).balance_url is not None
    if redact:
        # Members may view providers (to add keys) but must not see potentially
        # secret config such as custom auth headers.
        out.extra_headers = dict.fromkeys(out.extra_headers, "***")
    return out


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
    return [_to_out(p, redact=redact) for p in rows]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
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
        model_routes=[r.model_dump() for r in body.model_routes],
        added_by=user.id,
        added_by_name=actor_display_name(user),
    )
    session.add(provider)
    await session.flush()
    await record_audit(
        session,
        action="provider.create",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider.id,
        detail={"name": provider.name, "type": provider.type},
        ip=request.client.host if request.client else None,
    )
    await session.refresh(provider)
    return _to_out(provider)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProviderOut:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    _ensure_can_edit(user, provider)
    changes = body.model_dump(exclude_unset=True)
    if "proxy_mode" in changes or "proxy_ids" in changes:
        await _validate_proxy_config(
            session,
            changes.get("proxy_mode", provider.proxy_mode),
            changes.get("proxy_ids", provider.proxy_ids),
        )
    for field, value in changes.items():
        setattr(provider, field, value)
    await session.flush()
    await record_audit(
        session,
        action="provider.update",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider.id,
        detail={"changes": list(changes)},
        ip=request.client.host if request.client else None,
    )
    await session.refresh(provider)
    return _to_out(provider)


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
        action="provider.delete",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="provider",
        target_id=provider_id,
        detail={"name": provider.name},
        ip=request.client.host if request.client else None,
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
    path = body.path if body.path.startswith("/") else f"/{body.path}"
    url = f"{base}{path}"
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
