"""Platform announcements.

Any signed-in user may read announcements (they drive the login popup and the
dashboard home panel). Publishing is staff-only (owner / co-owner / admin). The
author is recorded and shown. An author may always edit/delete their own
announcement; a user may also manage announcements authored by a *lower*
permission tier (owner/co-owner share the top tier, so they cannot manage each
other's — matching the "same-tier peers can't act on one another" rule).

An announcement can target specific role groups. If ``target_role_group_ids``
is empty, everyone sees it. Otherwise only members of at least one listed group
receive it. Staff always see all announcements (for management).

Editing keeps a trail in the audit log; the previous and new title/body are
stored as an owner-revealable secret, like other secrets.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    audit_scope_for,
    get_current_user,
    is_staff,
    role_rank,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.models.db import Announcement, RoleGroupMembership, User
from voidswitch.models.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementUpdate,
)

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def _can_manage(user: User, ann: Announcement) -> bool:
    """True if ``user`` may edit/delete ``ann`` (own, or a lower-tier author's)."""
    if ann.created_by is not None and ann.created_by == user.id:
        return True
    return role_rank(user.role) > role_rank(ann.created_by_role)


def _to_out(user: User, ann: Announcement) -> AnnouncementOut:
    out = AnnouncementOut.model_validate(ann)
    out.can_manage = _can_manage(user, ann)
    return out


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    limit: int | None = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AnnouncementOut]:
    """List announcements newest-first. ``limit`` caps the count (for previews).

    Non-staff users only see announcements whose ``target_role_group_ids`` is
    empty (everyone) or includes at least one of the user's role groups.
    """
    stmt = select(Announcement).order_by(Announcement.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    if is_staff(user):
        return [_to_out(user, a) for a in rows]

    # Collect the user's role group ids.
    memberships = (
        (
            await session.execute(
                select(RoleGroupMembership.role_group_id).where(
                    RoleGroupMembership.user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    user_group_ids = set(memberships)

    result: list[AnnouncementOut] = []
    for a in rows:
        if not a.target_role_group_ids or user_group_ids & set(a.target_role_group_ids):
            result.append(_to_out(user, a))
    return result


@router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    body: AnnouncementCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> AnnouncementOut:
    if not is_staff(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only owner / co-owner / admin may publish announcements."
        )
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "title is required.")
    ann = Announcement(
        title=title,
        body=body.body,
        created_by=user.id,
        created_by_name=actor_display_name(user),
        created_by_role=user.role,
        target_role_group_ids=body.target_role_group_ids,
    )
    session.add(ann)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.ANNOUNCEMENT_CREATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="announcement",
        target_id=ann.id,
        detail={"title": ann.title},
        # The body may carry sensitive context; keep an owner-revealable copy.
        sensitive={"title": ann.title, "body": ann.body},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=audit_scope_for(user),
    )
    return _to_out(user, ann)


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    announcement_id: int,
    body: AnnouncementUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> AnnouncementOut:
    ann = await session.get(Announcement, announcement_id)
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    if not _can_manage(user, ann):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only edit your own announcements or those of a lower tier.",
        )
    old_title, old_body = ann.title, ann.body
    changed = False
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "title cannot be empty.")
        if title != ann.title:
            ann.title = title
            changed = True
    if body.body is not None and body.body != ann.body:
        ann.body = body.body
        changed = True
    if (
        body.target_role_group_ids is not None
        and body.target_role_group_ids != ann.target_role_group_ids
    ):
        ann.target_role_group_ids = body.target_role_group_ids
        changed = True
    if changed:
        ann.edited = True
        await session.flush()
        await record_audit(
            session,
            action=AuditAction.ANNOUNCEMENT_UPDATE,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            target_type="announcement",
            target_id=ann.id,
            detail={"title": ann.title, "author": ann.created_by_name},
            # Keep the full before/after content as an owner-revealable secret so
            # edits leave an auditable, reviewable trail without leaking content.
            sensitive={
                "old_title": old_title,
                "old_body": old_body,
                "new_title": ann.title,
                "new_body": ann.body,
            },
            secret_key=settings.server.secret_key,
            ip=request.client.host if request.client else None,
            scope=audit_scope_for(user),
        )
    return _to_out(user, ann)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> None:
    ann = await session.get(Announcement, announcement_id)
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    if not _can_manage(user, ann):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only delete your own announcements or those of a lower tier.",
        )
    await session.delete(ann)
    await record_audit(
        session,
        action=AuditAction.ANNOUNCEMENT_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="announcement",
        target_id=announcement_id,
        detail={"title": ann.title, "author": ann.created_by_name},
        sensitive={"title": ann.title, "body": ann.body},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=audit_scope_for(user),
    )
