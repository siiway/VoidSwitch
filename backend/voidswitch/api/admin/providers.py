"""Admin: provider CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus
from voidswitch.core.audit import record_audit
from voidswitch.core.auth import require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import Provider, User
from voidswitch.models.schemas import ProviderCreate, ProviderOut, ProviderUpdate
from voidswitch.services.providers.registry import adapter_catalog, adapter_class

router = APIRouter(prefix="/api/admin/providers", tags=["admin:providers"])


def _to_out(provider: Provider) -> ProviderOut:
    out = ProviderOut.model_validate(provider)
    out.key_count = len(provider.keys)
    out.active_key_count = sum(1 for k in provider.keys if k.status == KeyStatus.ACTIVE.value)
    return out


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[ProviderOut]:
    rows = (
        (await session.execute(select(Provider).order_by(Provider.priority, Provider.id)))
        .scalars()
        .all()
    )
    return [_to_out(p) for p in rows]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ProviderOut:
    existing = (
        await session.execute(select(Provider).where(Provider.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider name already exists.")

    cls = adapter_class(body.type)
    models = body.models or list(cls.default_models)
    base_url = body.base_url or cls.default_base_url

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
    user: User = Depends(require_staff),
) -> ProviderOut:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found.")
    changes = body.model_dump(exclude_unset=True)
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
    user: User = Depends(require_staff),
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
async def provider_catalog(_: User = Depends(require_staff)) -> list[dict[str, object]]:
    return adapter_catalog()
