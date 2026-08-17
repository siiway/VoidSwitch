"""Exposed models catalog + route flowcharts — visible to every signed-in user,
editable by staff.

Members get a read-only view of every *exposed* model and its metadata. Staff may
edit metadata (individually or in batch), wire the route flowcharts (exposed →
layer pools → upstream refs), and match models to the models.dev registry.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    audit_scope_for,
    get_current_user,
    is_staff,
    require_staff,
)
from voidswitch.core.database import get_session
from voidswitch.models.db import (
    ExposedModel,
    Provider,
    RoleGroup,
    Route,
    RouteLayer,
    RoutePoolEntry,
    User,
)
from voidswitch.models.schemas import (
    ModelBatchResult,
    ModelBatchUpdate,
    ModelCleanResult,
    ModelOut,
    ModelSyncResult,
    ModelUpsert,
    ModelWithRouteOut,
    RouteOut,
    RouteUpdate,
)
from voidswitch.services import model_routing, models_catalog, models_dev

router = APIRouter(prefix="/api/models", tags=["models"])


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base``, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _to_out(item: ExposedModel) -> ModelOut:
    upstreams = []
    route = item.route
    if route is not None:
        seen: set[tuple[int | None, str]] = set()
        for layer in route.layers:
            for entry in layer.entries:
                key = (entry.provider_id, entry.upstream_model)
                if key in seen:
                    continue
                seen.add(key)
                provider = entry.provider
                if provider is None:
                    continue
                slug = provider.slug or provider.name
                upstreams.append(
                    f"{slug}/{entry.upstream_model}" if entry.upstream_model else slug
                )
    return ModelOut(
        id=item.id,
        model_id=item.model_id,
        display_name=item.display_name,
        description=item.description,
        opencode_config=item.opencode_config or {},
        enabled=item.enabled,
        allowed_role_group_ids=list(item.allowed_role_group_ids or []),
        limit_context=item.limit_context,
        limit_input=item.limit_input,
        limit_output=item.limit_output,
        reasoning=item.reasoning,
        capabilities=item.capabilities or {},
        modalities=item.modalities or {},
        models_dev_id=item.models_dev_id,
        models_dev_synced_at=item.models_dev_synced_at,
        upstreams=upstreams,
        added_by_name=item.added_by_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _route_out(route: Route | None) -> RouteOut | None:
    if route is None:
        return None
    return RouteOut(
        id=route.id,
        exposed_model_id=route.exposed_model_id,
        layers=[
            {
                "id": layer.id,
                "position": layer.position,
                "max_attempts": layer.max_attempts,
                "entries": [
                    {
                        "id": e.id,
                        "provider_id": e.provider_id,
                        "provider_name": e.provider.name if e.provider else None,
                        "provider_slug": e.provider.slug if e.provider else None,
                        "upstream_model": e.upstream_model,
                        "weight": e.weight,
                        "enabled": e.enabled,
                        "key_pool": e.key_pool,
                    }
                    for e in layer.entries
                ],
            }
            for layer in route.layers
        ],
    )


@router.get("", response_model=list[ModelOut])
async def list_models(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ModelOut]:
    catalog = await models_catalog.build_catalog(session)
    # Members must not see hidden (disabled) models at all — only staff, who can
    # manage them, get the full list with the "unavailable (hidden)" badge.
    if not is_staff(user):
        catalog = [i for i in catalog if i.enabled]
    return [_to_out(i) for i in catalog]


async def _get_or_create_entry(
    session: AsyncSession, model_id: str, user: User
) -> ExposedModel:
    entry = (
        await session.execute(select(ExposedModel).where(ExposedModel.model_id == model_id))
    ).scalar_one_or_none()
    if entry is None:
        entry = ExposedModel(
            model_id=model_id,
            added_by=user.id,
            added_by_name=actor_display_name(user),
        )
        session.add(entry)
        await session.flush()
        await model_routing.get_or_create_route(session, entry)
    return entry


async def _validated_role_group_ids(
    session: AsyncSession, ids: list[int]
) -> list[int]:
    """Validate a role-group allow-list; reject unknown ids instead of silently
    dropping them."""
    existing = set(
        (
            await session.execute(select(RoleGroup.id).where(RoleGroup.builtin.is_(False)))
        )
        .scalars()
        .all()
    )
    unknown = sorted(set(ids) - existing)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown role group id(s): {unknown}.",
        )
    seen: set[int] = set()
    result: list[int] = []
    for gid in ids:
        if gid not in seen:
            seen.add(gid)
            result.append(gid)
    return result


@router.put("", response_model=ModelOut)
async def upsert_model(
    body: ModelUpsert,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelOut:
    model_id = body.model_id.strip()
    if not model_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "model_id is required.")
    entry = await _get_or_create_entry(session, model_id, user)
    for field, value in body.model_dump(exclude={"model_id"}, exclude_none=True).items():
        if field in ("limit_context", "limit_input", "limit_output"):
            setattr(entry, field, max(0, int(value)) if value else None)
            continue
        if field == "models_dev_id":
            entry.models_dev_id = value or None
            if value:
                entry.models_dev_synced_at = dt.datetime.now(dt.UTC)
            continue
        setattr(entry, field, value)
    if body.allowed_role_group_ids is not None:
        entry.allowed_role_group_ids = await _validated_role_group_ids(
            session, body.allowed_role_group_ids
        )
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_UPSERT,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model",
        target_id=entry.id,
        detail={
            "model_id": model_id,
            "changes": body.model_dump(exclude={"model_id"}, exclude_none=True),
        },
        ip=request.client.host if request.client else None,
    )
    entry = await session.get(ExposedModel, entry.id)
    return _to_out(entry)


@router.post("/batch", response_model=ModelBatchResult)
async def batch_update_models(
    body: ModelBatchUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelBatchResult:
    ids = [m.strip() for m in body.model_ids if m and m.strip()]
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "model_ids is required.")
    role_group_ids: list[int] | None = None
    if body.allowed_role_group_ids is not None:
        role_group_ids = await _validated_role_group_ids(
            session, body.allowed_role_group_ids
        )
    merge = body.opencode_config_mode != "overwrite"
    for model_id in ids:
        entry = await _get_or_create_entry(session, model_id, user)
        if body.description is not None:
            entry.description = body.description
        if body.opencode_config is not None:
            entry.opencode_config = (
                _deep_merge(entry.opencode_config or {}, body.opencode_config)
                if merge
                else body.opencode_config
            )
        if body.enabled is not None:
            entry.enabled = body.enabled
        if role_group_ids is not None:
            entry.allowed_role_group_ids = list(role_group_ids)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_BATCH_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model",
        detail={
            "model_ids": ids,
            "changes": body.model_dump(exclude={"model_ids"}, exclude_none=True),
        },
        ip=request.client.host if request.client else None,
    )
    return ModelBatchResult(updated=len(ids))


@router.post("/sync", response_model=ModelSyncResult)
async def sync_models(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelSyncResult:
    """Auto-expose every currently-served upstream id with a 1:1 route."""
    added, total = await models_catalog.sync_from_providers(
        session, added_by=user.id, added_by_name=actor_display_name(user)
    )
    if added:
        await record_audit(
            session,
            action=AuditAction.MODEL_SYNC,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            target_type="model",
            detail={"added": added, "total": total},
            ip=request.client.host if request.client else None,
            scope=audit_scope_for(user),
        )
    return ModelSyncResult(added=added, total=total)


@router.post("/clean", response_model=ModelCleanResult)
async def clean_unserved(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelCleanResult:
    """Delete exposed models whose route resolves to no enabled upstream."""
    deleted, ids = await models_catalog.clean_unserved(session)
    if deleted:
        await record_audit(
            session,
            action=AuditAction.MODEL_CLEAN_UNSERVED,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            target_type="model",
            detail={"deleted": deleted, "model_ids": ids},
            ip=request.client.host if request.client else None,
            scope=AuditScope.ADMIN.value,
        )
    return ModelCleanResult(deleted=deleted, model_ids=ids)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    entry = await session.get(ExposedModel, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model metadata not found.")
    model_id = entry.model_id
    await session.delete(entry)
    await record_audit(
        session,
        action=AuditAction.MODEL_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model",
        target_id=entry_id,
        detail={"model_id": model_id},
        ip=request.client.host if request.client else None,
    )


# --------------------------------------------------------------------------- #
# Route flowcharts (staff editor)
# --------------------------------------------------------------------------- #


async def _get_exposed(session: AsyncSession, model_id: str) -> ExposedModel:
    entry = (
        await session.execute(select(ExposedModel).where(ExposedModel.model_id == model_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exposed model not found.")
    return entry


@router.get("/{model_id}/route", response_model=ModelWithRouteOut)
async def get_route(
    model_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> ModelWithRouteOut:
    entry = await _get_exposed(session, model_id)
    route = await model_routing.resolve_route(session, entry)
    out = ModelWithRouteOut(**_to_out(entry).model_dump())
    out.route = _route_out(route)
    return out


@router.put("/{model_id}/route", response_model=ModelWithRouteOut)
async def update_route(
    model_id: str,
    body: RouteUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelWithRouteOut:
    entry = await _get_exposed(session, model_id)
    route = await model_routing.get_or_create_route(session, entry)
    provider_ids = {
        e.provider_id for layer in body.layers for e in layer.entries if e.provider_id
    }
    if provider_ids:
        found = set(
            (await session.execute(select(Provider.id).where(Provider.id.in_(provider_ids))))
            .scalars()
            .all()
        )
        missing = sorted(provider_ids - found)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown provider id(s): {missing}."
            )
    # Replace the whole flowchart.
    for layer in list(route.layers):
        await session.delete(layer)
    for pos, layer_in in enumerate(body.layers):
        layer = RouteLayer(
            route_id=route.id,
            position=pos,
            max_attempts=max(1, layer_in.max_attempts),
        )
        session.add(layer)
        await session.flush()
        for entry_in in layer_in.entries:
            session.add(
                RoutePoolEntry(
                    layer_id=layer.id,
                    provider_id=entry_in.provider_id,
                    upstream_model=(entry_in.upstream_model or "").strip(),
                    weight=max(1, entry_in.weight),
                    enabled=entry_in.enabled,
                    key_pool=(entry_in.key_pool or "").strip(),
                )
            )
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_UPSERT,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model",
        target_id=entry.id,
        detail={"model_id": model_id, "changes": {"route": body.model_dump()}},
        ip=request.client.host if request.client else None,
    )
    route = await model_routing.resolve_route(session, entry)
    out = ModelWithRouteOut(**_to_out(entry).model_dump())
    out.route = _route_out(route)
    return out


# --------------------------------------------------------------------------- #
# models.dev integration (staff)
# --------------------------------------------------------------------------- #


@router.get("/models-dev/search")
async def models_dev_search(
    q: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> dict:
    rows = (
        (await session.execute(select(models_dev.ModelsDevCache))).scalars().all()
        if models_dev.sync_enabled()
        else []
    )
    results = models_dev.search_cached(rows, q)
    return {
        "results": results,
        "synced": models_dev.sync_enabled(),
    }


@router.post("/models-dev/sync")
async def models_dev_sync_now(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> dict:
    count = await models_dev.sync_now(session)
    await record_audit(
        session,
        action=AuditAction.MODEL_SYNC,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="models_dev",
        detail={"synced": count},
        ip=request.client.host if request.client else None,
        scope=audit_scope_for(user),
    )
    return {"synced": count}