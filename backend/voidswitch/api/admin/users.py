"""Admin: user listing and role/enable management.

Viewing the user list is staff-level. *Mutating* a user — granting the local
admin override or disabling an account — is owner-only.
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
    require_owner,
    require_staff,
    role_rank,
)
from voidswitch.core.database import get_session
from voidswitch.models.db import User
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


def _to_user_out(u: User) -> UserOut:
    out = UserOut.model_validate(u)
    # Role-group names come from the user's (auto/manual) memberships; the
    # built-in moderator group is never stored there, so this lists only the
    # custom groups that gate model access.
    out.role_group_names = sorted(
        m.group.name for m in u.group_memberships if m.group is not None
    )
    return out


@router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[UserOut]:
    rows = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return [_to_user_out(u) for u in rows]


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


@router.post("/{user_id}/force-logout", response_model=UserOut)
async def force_logout_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if target.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot force logout yourself.")
    if role_rank(actor.role) <= role_rank(target.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only force logout users below your role tier.",
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
