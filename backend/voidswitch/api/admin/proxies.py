"""Admin: outbound proxy pool management."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import ProxyStatus
from voidswitch.core.audit import record_audit
from voidswitch.core.auth import actor_display_name, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import Provider, Proxy, User
from voidswitch.models.schemas import ProxyCreate, ProxyOut, ProxyUpdate
from voidswitch.services.network import Route, probe_route

router = APIRouter(prefix="/api/admin/proxies", tags=["admin:proxies"])


@router.get("", response_model=list[ProxyOut])
async def list_proxies(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[Proxy]:
    rows = (await session.execute(select(Proxy).order_by(Proxy.id))).scalars().all()
    return list(rows)


@router.post("", response_model=list[ProxyOut], status_code=status.HTTP_201_CREATED)
async def add_proxies(
    body: ProxyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[Proxy]:
    existing = {u for (u,) in (await session.execute(select(Proxy.url))).all()}
    created: list[Proxy] = []
    seen: set[str] = set()
    for raw in body.urls:
        url = raw.strip()
        if not url or url in existing or url in seen:
            continue
        seen.add(url)
        proxy = Proxy(
            url=url,
            local_address=body.local_address,
            weight=body.weight,
            note=body.note,
            status=ProxyStatus.ACTIVE.value,
        )
        session.add(proxy)
        created.append(proxy)
    if not created:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No new proxies to add.")
    await session.flush()
    await record_audit(
        session,
        action="proxy.add",
        actor_sub=user.sub,
        actor_name=user.name,
        target_type="proxy",
        detail={"added": len(created)},
        ip=request.client.host if request.client else None,
    )
    return created


@router.patch("/{proxy_id}", response_model=ProxyOut)
async def update_proxy(
    proxy_id: int,
    body: ProxyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> Proxy:
    proxy = await session.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proxy not found.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("enabled") is True or changes.get("status") == ProxyStatus.ACTIVE.value:
        proxy.failed_count = 0
        proxy.disabled_reason = None
        proxy.status = ProxyStatus.ACTIVE.value
    for field, value in changes.items():
        if field == "enabled":
            continue
        setattr(proxy, field, value)
    if "enabled" in changes:
        proxy.enabled = changes["enabled"]
    await session.flush()
    await record_audit(
        session,
        action="proxy.update",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="proxy",
        target_id=proxy_id,
        detail={"changes": list(changes)},
        ip=request.client.host if request.client else None,
    )
    return proxy


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    proxy = await session.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proxy not found.")
    # Scrub this id from any provider's selected proxy_ids so no dangling
    # reference is left behind. (proxy_ids is JSON — there's no FK to cascade.)
    providers = (await session.execute(select(Provider))).scalars().all()
    for p in providers:
        if p.proxy_ids and proxy_id in p.proxy_ids:
            p.proxy_ids = [pid for pid in p.proxy_ids if pid != proxy_id]
    await record_audit(
        session,
        action="proxy.delete",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="proxy",
        target_id=proxy_id,
        detail={"url": proxy.url},
        ip=request.client.host if request.client else None,
    )
    await session.delete(proxy)


@router.post("/{proxy_id}/probe", response_model=ProxyOut)
async def probe_proxy(
    proxy_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> Proxy:
    proxy = await session.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proxy not found.")
    route = Route(proxy_url=proxy.url or None, local_address=proxy.local_address)
    ok, latency, _status, error = await probe_route(route, "https://api.openai.com/v1/models")
    proxy.last_checked_at = dt.datetime.now(dt.UTC)
    proxy.latency_ms = latency
    if ok:
        proxy.status = ProxyStatus.ACTIVE.value
        proxy.failed_count = 0
        proxy.disabled_reason = None
    else:
        proxy.disabled_reason = error
    await session.flush()
    await record_audit(
        session,
        action="proxy.probe",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="proxy",
        target_id=proxy_id,
        detail={"ok": ok, "latency_ms": latency},
        ip=request.client.host if request.client else None,
    )
    return proxy
