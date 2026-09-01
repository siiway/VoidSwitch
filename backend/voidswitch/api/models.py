"""Exposed models catalog + route flowcharts — visible to every signed-in user,
editable by staff.

Members get a read-only view of every *exposed* model and its metadata. Staff may
edit metadata (individually or in batch), wire the route flowcharts (exposed →
layer pools → upstream refs), and match models to the models.dev registry.
"""

from __future__ import annotations

import datetime as dt
import re

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
    ModelCategory,
    Provider,
    RoleGroup,
    Route,
    RouteLayer,
    RoutePoolEntry,
    User,
)
from voidswitch.models.schemas import (
    ModelBatchDelete,
    ModelBatchResult,
    ModelBatchUpdate,
    ModelCategoryCreate,
    ModelCategoryOut,
    ModelCategoryUpdate,
    ModelCleanResult,
    ModelOut,
    ModelUpsert,
    ModelWithRouteOut,
    RouteOut,
    RouteUpdate,
)
from voidswitch.services import model_routing, models_catalog, models_dev

router = APIRouter(prefix="/api/models", tags=["models"])

_PASSTHROUGH_RE = re.compile(
    r"^(?P<exposed>[^\s@]+?)(?:\s*=>\s*(?P<upstream>[^\s@]+?))?(?:\s*@\s*(?P<pool>\S+))?$"
)


def _parse_passthrough_entry(entry: str) -> dict[str, str]:
    """Parse a passthrough whitelist entry into its components."""
    m = _PASSTHROUGH_RE.match(entry.strip())
    if m is None:
        return {"exposed": entry.strip(), "upstream": entry.strip(), "pool": ""}
    exposed = (m.group("exposed") or "").strip()
    upstream = (m.group("upstream") or exposed).strip()
    pool = (m.group("pool") or "").strip()
    return {"exposed": exposed, "upstream": upstream, "pool": pool}


def _slugify_category(name: str) -> str:
    """A stable category slug from a name (mirrors the provider slugify)."""
    out: list[str] = []
    for ch in (name or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "category"


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


def _to_out(
    item: ExposedModel,
    *,
    providers_by_id: dict[int, Provider] | None = None,
) -> ModelOut:
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
                upstreams.append(f"{slug}/{entry.upstream_model}" if entry.upstream_model else slug)
    unserved = (
        models_catalog.is_unserved(item, providers_by_id) if providers_by_id is not None else False
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
        brand=item.brand,
        upstreams=upstreams,
        added_by_name=item.added_by_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
        category_id=item.category_id,
        category_name=item.category.name if item.category is not None else None,
        category_slug=item.category.slug if item.category is not None else None,
        unserved=unserved,
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
    catalog_by_id = {item.model_id: item for item in catalog}

    # Passthrough virtual entries: each provider with passthrough_enabled
    # contributes its whitelisted models as ``provider-slug/exposed-model-id``.
    # A passthrough id *takes over* the matching exposed-model id so the catalog
    # never shows the same id twice (a leftover exposed-model row from the old
    # 1:1 sync would otherwise render alongside its passthrough twin). Any
    # ExposedModel row saved for the passthrough id (created the first time an
    # operator edits its metadata or access) is *merged* into the virtual entry
    # so edits actually surface in the catalog.
    passthrough_providers = (
        (
            await session.execute(
                select(Provider).where(
                    Provider.enabled.is_(True), Provider.passthrough_enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    passthrough_ids: set[str] = set()
    virtual: list[ModelOut] = []
    virtual_id = -1
    for provider in passthrough_providers:
        seen: set[str] = set()
        for entry in provider.passthrough_models or []:
            parsed = _parse_passthrough_entry(entry)
            exposed_id = parsed["exposed"]
            model_id = f"{provider.slug}/{exposed_id}"
            if model_id in seen:
                continue
            seen.add(model_id)
            passthrough_ids.add(model_id)

            existing = catalog_by_id.get(model_id)
            if existing is not None:
                # Members must not see hidden (disabled) models at all — even
                # for passthrough ids that would otherwise be surfaced by the
                # provider whitelist.
                if not is_staff(user) and not existing.enabled:
                    continue
                # Merge the saved metadata into the virtual entry. ``unserved``
                # is meaningless for passthrough (the provider forwards the id
                # directly), so it stays False.
                out = _to_out(existing)
                out.provider = True
                out.category_name = provider.name
                out.category_slug = provider.slug
                if not out.display_name:
                    out.display_name = exposed_id
                virtual.append(out)
            else:
                virtual.append(
                    ModelOut(
                        id=virtual_id,
                        model_id=model_id,
                        display_name=exposed_id,
                        enabled=True,
                        category_name=provider.name,
                        category_slug=provider.slug,
                        provider=True,
                    )
                )
                virtual_id -= 1

    # Enabled providers by id, used to flag unserved exposed models.
    enabled_providers = {
        p.id: p
        for p in (
            (await session.execute(select(Provider).where(Provider.enabled.is_(True))))
            .scalars()
            .all()
        )
    }

    result: list[ModelOut] = []
    for item in catalog:
        # Members must not see hidden (disabled) models at all.
        if not is_staff(user) and not item.enabled:
            continue
        # Passthrough serves these ids directly — drop any stale duplicate.
        if item.model_id in passthrough_ids:
            continue
        result.append(_to_out(item, providers_by_id=enabled_providers))
    result.extend(virtual)

    return result


async def _get_or_create_entry(session: AsyncSession, model_id: str, user: User) -> ExposedModel:
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


async def _validated_role_group_ids(session: AsyncSession, ids: list[int]) -> list[int]:
    """Validate a role-group allow-list; reject unknown ids instead of silently
    dropping them."""
    existing = set(
        (await session.execute(select(RoleGroup.id).where(RoleGroup.builtin.is_(False))))
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


async def _validate_category_id(session: AsyncSession, category_id: int | None) -> int | None:
    """Validate a category id; reject unknown ids."""
    if category_id is None:
        return None
    exists = (
        await session.execute(select(ModelCategory.id).where(ModelCategory.id == category_id))
    ).first()
    if exists is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown category id: {category_id}.",
        )
    return category_id


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
        if field == "brand":
            entry.brand = value or None
            continue
        if field == "category_id":
            entry.category_id = await _validate_category_id(session, value)
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
    # Expire + re-select so selectin relationships (route → layers → entries)
    # reload. session.get alone returns the identity-map instance whose route
    # may still be unloaded after get_or_create_route; accessing it in sync
    # _to_out raises MissingGreenlet under asyncpg. Capture the PK before
    # expire — reading entry.id afterwards would itself lazy-load.
    entry_id = entry.id
    session.expire(entry)
    entry = (
        await session.execute(select(ExposedModel).where(ExposedModel.id == entry_id))
    ).scalar_one()
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
        role_group_ids = await _validated_role_group_ids(session, body.allowed_role_group_ids)
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


@router.post("/batch-delete", response_model=ModelCleanResult)
async def batch_delete_models(
    body: ModelBatchDelete,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelCleanResult:
    """Delete many models by public id (exposed rows and/or passthrough entries)."""
    ids = [m.strip() for m in body.model_ids if m and m.strip()]
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "model_ids is required.")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for mid in ids:
        if mid in seen:
            continue
        seen.add(mid)
        ordered.append(mid)

    removed: list[str] = []
    # Passthrough: strip matching whitelist entries from each provider.
    passthrough_providers = (
        (await session.execute(select(Provider).where(Provider.passthrough_enabled.is_(True))))
        .scalars()
        .all()
    )
    for mid in ordered:
        slash = mid.find("/")
        if slash <= 0:
            continue
        slug, exposed = mid[:slash], mid[slash + 1 :]
        for provider in passthrough_providers:
            if provider.slug != slug:
                continue
            kept: list[str] = []
            hit = False
            for entry in provider.passthrough_models or []:
                parsed = _parse_passthrough_entry(entry)
                if parsed["exposed"] == exposed:
                    hit = True
                    continue
                kept.append(entry)
            if hit:
                provider.passthrough_models = kept
                if mid not in removed:
                    removed.append(mid)

    # Exposed-model rows (also covers leftover metadata for passthrough ids).
    rows = (
        (await session.execute(select(ExposedModel).where(ExposedModel.model_id.in_(ordered))))
        .scalars()
        .all()
    )
    for entry in rows:
        if entry.model_id not in removed:
            removed.append(entry.model_id)
        await session.delete(entry)

    if removed:
        await session.flush()
        await record_audit(
            session,
            action=AuditAction.MODEL_DELETE,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            target_type="model",
            detail={"model_ids": removed, "batch": True},
            ip=request.client.host if request.client else None,
        )
    return ModelCleanResult(deleted=len(removed), model_ids=removed)


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


@router.delete("/passthrough/{slug}/{exposed}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passthrough_model(
    slug: str,
    exposed: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    """Remove a passthrough model from its provider's whitelist.

    The model's id is ``slug/exposed``. Deletes the matching entry(ies) from the
    provider's ``passthrough_models`` list and drops any stale exposed-model
    metadata row carrying the same id.
    """
    provider = (
        await session.execute(
            select(Provider).where(Provider.slug == slug, Provider.passthrough_enabled.is_(True))
        )
    ).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passthrough provider not found.")
    kept: list[str] = []
    removed = 0
    for entry in provider.passthrough_models or []:
        parsed = _parse_passthrough_entry(entry)
        if parsed["exposed"] == exposed:
            removed += 1
            continue
        kept.append(entry)
    if removed:
        provider.passthrough_models = kept
    # Clean any leftover exposed-model metadata for this id.
    stale = (
        await session.execute(
            select(ExposedModel).where(ExposedModel.model_id == f"{slug}/{exposed}")
        )
    ).scalar_one_or_none()
    if stale is not None:
        await session.delete(stale)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model",
        detail={
            "model_id": f"{slug}/{exposed}",
            "provider_id": provider.id,
            "passthrough_removed": removed,
        },
        ip=request.client.host if request.client else None,
    )


# --------------------------------------------------------------------------- #
# Model categories
# --------------------------------------------------------------------------- #


@router.get("/categories", response_model=list[ModelCategoryOut])
async def list_categories(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[ModelCategoryOut]:
    rows = (
        (await session.execute(select(ModelCategory).order_by(ModelCategory.position)))
        .scalars()
        .all()
    )
    return [ModelCategoryOut.model_validate(r) for r in rows]


@router.post("/categories", response_model=ModelCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: ModelCategoryCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelCategoryOut:
    existing = (
        await session.execute(select(ModelCategory).where(ModelCategory.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Category name already exists.")
    slug = _slugify_category(body.name)
    cat = ModelCategory(name=body.name, slug=slug, position=body.position)
    session.add(cat)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_CATEGORY_CREATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model_category",
        target_id=cat.id,
        detail={"name": cat.name, "slug": cat.slug, "position": cat.position},
        ip=request.client.host if request.client else None,
    )
    await session.refresh(cat)
    return ModelCategoryOut.model_validate(cat)


@router.patch("/categories/{category_id}", response_model=ModelCategoryOut)
async def update_category(
    category_id: int,
    body: ModelCategoryUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> ModelCategoryOut:
    cat = await session.get(ModelCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        existing = (
            await session.execute(
                select(ModelCategory.id).where(
                    ModelCategory.name == changes["name"], ModelCategory.id != category_id
                )
            )
        ).first()
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Category name already exists.")
        cat.name = changes["name"]
        cat.slug = _slugify_category(changes["name"])
    if "position" in changes:
        cat.position = changes["position"]
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.MODEL_CATEGORY_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model_category",
        target_id=cat.id,
        detail={"name": cat.name, "changes": changes},
        ip=request.client.host if request.client else None,
    )
    await session.refresh(cat)
    return ModelCategoryOut.model_validate(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    cat = await session.get(ModelCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    await session.delete(cat)
    await record_audit(
        session,
        action=AuditAction.MODEL_CATEGORY_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="model_category",
        target_id=category_id,
        detail={"name": cat.name},
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
    provider_ids = {e.provider_id for layer in body.layers for e in layer.entries if e.provider_id}
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
    results = models_dev.search_models(rows, q)
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
