"""Models catalog — visible to every signed-in user, editable by staff.

Members get a read-only, card-friendly view of every available model id and its
description / OpenCode config. Staff may edit descriptions and the custom
OpenCode model config (individually or in batch). Any signed-in user may refresh
the catalog from the providers (also reachable from the OpenCode ``/models``
command via the gateway endpoint in ``api.proxy``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    audit_scope_for,
    get_current_user,
    require_staff,
)
from voidswitch.core.database import get_session
from voidswitch.models.db import ModelEntry, RoleGroup, User
from voidswitch.models.schemas import (
    ModelBatchResult,
    ModelBatchUpdate,
    ModelCleanResult,
    ModelOut,
    ModelSyncResult,
    ModelUpsert,
)
from voidswitch.services import models_catalog

router = APIRouter(prefix="/api/models", tags=["models"])


def _to_out(item: models_catalog.CatalogItem) -> ModelOut:
    entry = item.entry
    return ModelOut(
        id=entry.id if entry is not None else None,
        model_id=item.model_id,
        mapped_id=item.mapped_id,
        public_id=item.public_id,
        display_name=entry.display_name if entry is not None else None,
        description=entry.description if entry is not None else None,
        opencode_config=entry.opencode_config if entry is not None else {},
        enabled=item.enabled,
        allowed_role_group_ids=(
            list(entry.allowed_role_group_ids or []) if entry is not None else []
        ),
        providers=item.providers,
        served=item.served,
        registered=item.registered,
        added_by_name=entry.added_by_name if entry is not None else None,
        created_at=entry.created_at if entry is not None else None,
        updated_at=entry.updated_at if entry is not None else None,
    )


@router.get("", response_model=list[ModelOut])
async def list_models(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[ModelOut]:
    catalog = await models_catalog.build_catalog(session)
    return [_to_out(i) for i in catalog]


async def _get_or_create_entry(
    session: AsyncSession, model_id: str, user: User
) -> ModelEntry:
    entry = (
        await session.execute(select(ModelEntry).where(ModelEntry.model_id == model_id))
    ).scalar_one_or_none()
    if entry is None:
        entry = ModelEntry(
            model_id=model_id,
            added_by=user.id,
            added_by_name=actor_display_name(user),
        )
        session.add(entry)
    return entry


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
    if body.mapped_id is not None:
        mapped = body.mapped_id.strip()
        if mapped == model_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "mapped_id must differ from the model id "
                "(use it to rename, not to alias to itself).",
            )
        entry.mapped_id = mapped or None
    if body.display_name is not None:
        entry.display_name = body.display_name.strip() or None
    if body.description is not None:
        entry.description = body.description
    if body.opencode_config is not None:
        entry.opencode_config = body.opencode_config
    if body.enabled is not None:
        entry.enabled = body.enabled
    if body.allowed_role_group_ids is not None:
        # Drop ids that no longer exist (e.g. a deleted group) and the built-in
        # moderator group (always allowed, never stored).
        valid_ids = set(
            (
                await session.execute(
                    select(RoleGroup.id).where(RoleGroup.builtin.is_(False))
                )
            )
            .scalars()
            .all()
        )
        entry.allowed_role_group_ids = [
            gid for gid in body.allowed_role_group_ids if gid in valid_ids
        ]
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
    catalog = await models_catalog.build_catalog(session)
    item = next((i for i in catalog if i.model_id == model_id), None)
    if item is None:  # pragma: no cover - just-written row is always present
        item = models_catalog.CatalogItem(model_id=model_id, entry=entry, providers=[])
    return _to_out(item)


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
    for model_id in ids:
        entry = await _get_or_create_entry(session, model_id, user)
        if body.description is not None:
            entry.description = body.description
        if body.opencode_config is not None:
            entry.opencode_config = body.opencode_config
        if body.enabled is not None:
            entry.enabled = body.enabled
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
    user: User = Depends(get_current_user),
) -> ModelSyncResult:
    """Register a metadata row for every served model id that lacks one.

    Open to any signed-in user (it only discovers what providers already serve),
    so the OpenCode ``/models`` command can keep the catalog fresh.
    """
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
    """Delete metadata for every model id no enabled provider currently serves.

    Staff-only (it is destructive). Returns the deleted count and the sorted
    list of model ids that were removed.
    """
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
    entry = await session.get(ModelEntry, entry_id)
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
