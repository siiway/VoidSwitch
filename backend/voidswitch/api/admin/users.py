"""Admin: user listing and role/enable management.

Reading the user list is open to staff and to role-group admins (the latter
see only their groups' members). *Mutating* a user — granting the local admin
override or disabling an account — is owner-only. *Force-logout* is open to
staff and to role-group admins, with extra guards so a group admin can't kick
staff or peer group-admins.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import (
    LOCAL_ASSIGNABLE_ROLES,
    OWNER_ROLES,
    actor_display_name,
    is_role_group_admin,
    is_staff,
    managed_group_ids,
    require_owner,
    require_staff_or_role_group_admin,
    role_rank,
)
from voidswitch.core.database import get_session
from voidswitch.models.db import RoleGroupAdminship, RoleGroupMembership, User
from voidswitch.models.schemas import UserOut

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])


class UserUpdate(BaseModel):
    role: str | None = None
    enabled: bool | None = None


def _auto_disable_tokens(target: User) -> int:
    disabled = 0
    for token in target.tokens:
        if token.deleted or not token.enabled:
            continue
        token.enabled = False
        token.auto_disabled = True
        disabled += 1
    target.void_tokens_admin_disabled = True
    return disabled


def _to_user_out(u: User, visible_groups: set[int] | None) -> UserOut:
    """Serialise ``u`` for the caller.

    ``visible_groups=None`` → the caller sees everything (staff). The full
    role-group name list is returned unchanged, and ``visible_via_group_ids``
    is the user's actual membership set (so the frontend can render chips
    identically for both callers).

    ``visible_groups=set(...)`` → the caller is a role-group admin. The
    user's ``role_group_names`` is filtered down to the *intersection* with
    the caller's managed groups (so we never leak that this user is also in
    some *other* organisation's group), and ``visible_via_group_ids`` shows
    only the same intersection.
    """
    out = UserOut.model_validate(u)
    all_membership_ids = [m.role_group_id for m in u.group_memberships if m.group is not None]
    all_membership_names = {
        m.role_group_id: m.group.name for m in u.group_memberships if m.group is not None
    }
    if visible_groups is None:
        # Staff: full membership set + names.
        out.role_group_names = sorted(all_membership_names.values())
        out.visible_via_group_ids = sorted(all_membership_ids)
    else:
        visible_ids = sorted(gid for gid in all_membership_ids if gid in visible_groups)
        out.role_group_names = sorted(all_membership_names[gid] for gid in visible_ids)
        out.visible_via_group_ids = visible_ids
    return out


@router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    caller: User = Depends(require_staff_or_role_group_admin),
) -> list[UserOut]:
    """List users.

    Staff callers get every user. A role-group admin caller gets only the
    union of their managed groups' members — the query filters on
    :class:`RoleGroupMembership` so a user who is *only* an admin of some
    other group they share isn't leaked.
    """
    if is_staff(caller):
        rows = (await session.execute(select(User).order_by(User.id))).scalars().all()
        return [_to_user_out(u, None) for u in rows]

    managed = managed_group_ids(caller)
    if not managed:
        # Defensive: require_staff_or_role_group_admin already filters this
        # out, but if a caller with empty managed set ever reaches here just
        # return nothing rather than exposing the full list.
        return []
    visible_user_ids_stmt = (
        select(RoleGroupMembership.user_id)
        .where(RoleGroupMembership.role_group_id.in_(managed))
        .distinct()
    )
    rows = (
        (
            await session.execute(
                select(User).where(User.id.in_(visible_user_ids_stmt)).order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    return [_to_user_out(u, managed) for u in rows]


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    changes: dict[str, object] = {}

    if body.role is not None and body.role != target.role:
        # Only the local-override roles can be set here. Owner/co-owner are
        # authoritative from Prism (or a direct DB edit) and must not be granted
        # or revoked through the dashboard.
        if body.role not in LOCAL_ASSIGNABLE_ROLES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Only 'admin' or 'member' can be set here; owner/co-owner come from Prism.",
            )
        if target.role in OWNER_ROLES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot change an owner/co-owner's role here; manage it in Prism or the database.",
            )
        if target.id == actor.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot change your own role.")
        changes["role"] = body.role
        target.role = body.role

    if body.enabled is not None and body.enabled != target.enabled:
        if target.id == actor.id and not body.enabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot disable yourself.")
        # Peers of the same (owner) tier must not be able to disable one another.
        # Only owners/co-owners reach this endpoint (require_owner), so refuse
        # disabling any account that is itself owner-tier.
        if not body.enabled and target.role in OWNER_ROLES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot disable an owner/co-owner; same-tier members can't disable each other.",
            )
        changes["enabled"] = body.enabled
        target.enabled = body.enabled
        if not body.enabled:
            # Disabling: force every dashboard session out (bump the epoch so any
            # outstanding JWT is rejected) and turn off all the user's Void-Tokens
            # so they can't keep calling the gateway. Remember to re-enable the
            # tokens at the user's next successful login (after re-enabling the
            # account), which re-evaluates their role/groups.
            target.session_epoch = (target.session_epoch or 0) + 1
            changes["void_tokens_disabled"] = _auto_disable_tokens(target)
        # Re-enabling does NOT immediately reactivate the Void-Tokens: they stay
        # off until the user logs in again, which forces a fresh role evaluation.

    if changes:
        await record_audit(
            session,
            action=AuditAction.USER_UPDATE,
            actor_sub=actor.sub,
            actor_name=actor_display_name(actor),
            target_type="user",
            target_id=target.id,
            detail={"target_name": actor_display_name(target), "changes": changes},
            ip=request.client.host if request.client else None,
        )

    await session.flush()
    return target


async def _target_shares_admin_group_with(
    session: AsyncSession, actor: User, target_id: int
) -> bool:
    """True when ``target`` is a role-group admin of a group ``actor`` also administers.

    Used to reject peer-vs-peer force-logout: a role-group admin can bounce
    their group's regular members, but not fellow admins of the same group —
    that class of "am I allowed to kick a peer?" question stays with staff.
    """
    actor_managed = managed_group_ids(actor)
    if not actor_managed:
        return False
    row = (
        await session.execute(
            select(RoleGroupAdminship.id).where(
                RoleGroupAdminship.user_id == target_id,
                RoleGroupAdminship.role_group_id.in_(actor_managed),
            )
        )
    ).first()
    return row is not None


async def _target_visible_to_group_admin(
    session: AsyncSession, actor: User, target_id: int
) -> bool:
    """True when ``target`` is a member of at least one group ``actor`` administers."""
    actor_managed = managed_group_ids(actor)
    if not actor_managed:
        return False
    row = (
        await session.execute(
            select(RoleGroupMembership.id).where(
                RoleGroupMembership.user_id == target_id,
                RoleGroupMembership.role_group_id.in_(actor_managed),
            )
        )
    ).first()
    return row is not None


@router.post("/{user_id}/force-logout", response_model=UserOut)
async def force_logout_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff_or_role_group_admin),
) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if target.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot force logout yourself.")

    if is_staff(actor):
        # Existing rule: staff may only force-logout users below their tier.
        if role_rank(actor.role) <= role_rank(target.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only force logout users below your role tier.",
            )
    else:
        # Role-group admin path (non-staff): target must be a member of a group
        # this actor administers, and must not be staff or a peer admin of the
        # same group. Force-logout here is essentially "refresh their membership
        # / adminship at their next login"; it's deliberately not a management
        # action against another observer.
        if not is_role_group_admin(actor):
            # Defensive — the guard already covers this.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted.")
        if is_staff(target):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Cannot force logout a platform moderator.",
            )
        if not await _target_visible_to_group_admin(session, actor, target.id):
            # Same 403 rather than 404 to avoid a "does this user id exist"
            # oracle for cross-organisation guessing.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This user is not in a role group you administer.",
            )
        if await _target_shares_admin_group_with(session, actor, target.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Cannot force logout another admin of a role group you share.",
            )

    target.session_epoch = (target.session_epoch or 0) + 1
    disabled = _auto_disable_tokens(target)
    await record_audit(
        session,
        action=AuditAction.AUTH_FORCE_LOGOUT,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="user",
        target_id=target.id,
        detail={"target_name": actor_display_name(target), "void_tokens_disabled": disabled},
        ip=request.client.host if request.client else None,
    )
    await session.flush()
    return target
