"""Moderator: manage role groups ("身份组") and their team→role auto-mappings.

A role group determines which models its members may call (see the models
catalog). Membership is granted automatically at login from the team mappings
defined here. The built-in ``moderator`` group is read-only — owner/co-owner/
admin belong to it implicitly and may always call every model.

Owner / co-owner / admin (the moderators) may manage role groups.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import TEAM_ROLE_RANK
from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import actor_display_name, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import RoleGroup, RoleGroupMapping, RoleGroupMembership, User
from voidswitch.models.schemas import (
    RoleGroupCreate,
    RoleGroupMappingOut,
    RoleGroupMemberOut,
    RoleGroupOut,
    RoleGroupUpdate,
)
from voidswitch.services.role_groups import normalise_team_role

router = APIRouter(prefix="/api/admin/role-groups", tags=["admin:role-groups"])

# Team roles that may be used in a mapping's ``min_role``.
_VALID_MIN_ROLES = {"owner", "co-owner", "admin", "member"}


def _validated_min_role(value: str) -> str:
    canonical = normalise_team_role(value)
    if canonical is None or canonical not in TEAM_ROLE_RANK:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid team role '{value}'. Use owner / co-owner / admin / member.",
        )
    return canonical


async def _member_counts(session: AsyncSession) -> dict[int, int]:
    rows = (
        await session.execute(
            select(
                RoleGroupMembership.role_group_id, func.count(RoleGroupMembership.id)
            ).group_by(RoleGroupMembership.role_group_id)
        )
    ).all()
    return {gid: int(count) for gid, count in rows}


def _to_out(group: RoleGroup, member_count: int) -> RoleGroupOut:
    return RoleGroupOut(
        id=group.id,
        slug=group.slug,
        name=group.name,
        description=group.description,
        builtin=group.builtin,
        mappings=[
            RoleGroupMappingOut(id=m.id, team_id=m.team_id, min_role=m.min_role)
            for m in sorted(group.mappings, key=lambda m: m.id)
        ],
        member_count=member_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("", response_model=list[RoleGroupOut])
async def list_role_groups(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[RoleGroupOut]:
    groups = (
        (await session.execute(select(RoleGroup).order_by(RoleGroup.builtin.desc(), RoleGroup.id)))
        .scalars()
        .all()
    )
    counts = await _member_counts(session)
    # Built-in moderator "membership" is derived from the user role, not stored;
    # surface the live count of staff users so the card isn't misleadingly empty.
    staff_count = (
        await session.execute(
            select(func.count(User.id)).where(User.role.in_(["owner", "co-owner", "admin"]))
        )
    ).scalar_one()
    out: list[RoleGroupOut] = []
    for g in groups:
        count = int(staff_count) if g.builtin else counts.get(g.id, 0)
        out.append(_to_out(g, count))
    return out


@router.post("", response_model=RoleGroupOut, status_code=status.HTTP_201_CREATED)
async def create_role_group(
    body: RoleGroupCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> RoleGroupOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name is required.")
    clash = (
        await session.execute(select(RoleGroup).where(RoleGroup.name == name))
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role group with this name already exists.")
    group = RoleGroup(name=name, description=(body.description or None), builtin=False)
    session.add(group)
    await session.flush()
    for m in body.mappings:
        team_id = m.team_id.strip()
        if not team_id:
            continue
        session.add(
            RoleGroupMapping(
                role_group_id=group.id,
                team_id=team_id,
                min_role=_validated_min_role(m.min_role),
            )
        )
    await session.flush()
    await session.refresh(group)
    await record_audit(
        session,
        action=AuditAction.ROLE_GROUP_CREATE,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="role_group",
        target_id=group.id,
        detail={"name": name, "mappings": [m.model_dump() for m in body.mappings]},
        ip=request.client.host if request.client else None,
    )
    return _to_out(group, 0)


@router.patch("/{group_id}", response_model=RoleGroupOut)
async def update_role_group(
    group_id: int,
    body: RoleGroupUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> RoleGroupOut:
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if group.builtin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The built-in moderator group cannot be edited.",
        )

    changes: dict[str, object] = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be empty.")
        if name != group.name:
            clash = (
                await session.execute(
                    select(RoleGroup).where(RoleGroup.name == name, RoleGroup.id != group.id)
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "A role group with this name already exists."
                )
            group.name = name
            changes["name"] = name
    if body.description is not None:
        group.description = body.description or None
        changes["description"] = group.description

    if body.mappings is not None:
        for existing in list(group.mappings):
            await session.delete(existing)
        await session.flush()
        new_mappings = []
        seen: set[tuple[str, str]] = set()
        for m in body.mappings:
            team_id = m.team_id.strip()
            if not team_id:
                continue
            min_role = _validated_min_role(m.min_role)
            # De-duplicate: the table enforces (role_group_id, team_id, min_role)
            # uniqueness, so a duplicate entry in the batch would 500 on flush.
            if (team_id, min_role) in seen:
                continue
            seen.add((team_id, min_role))
            session.add(
                RoleGroupMapping(role_group_id=group.id, team_id=team_id, min_role=min_role)
            )
            new_mappings.append({"team_id": team_id, "min_role": min_role})
        changes["mappings"] = new_mappings

    await session.flush()
    await session.refresh(group)
    if changes:
        await record_audit(
            session,
            action=AuditAction.ROLE_GROUP_UPDATE,
            actor_sub=actor.sub,
            actor_name=actor_display_name(actor),
            target_type="role_group",
            target_id=group.id,
            detail={"name": group.name, "changes": changes},
            ip=request.client.host if request.client else None,
        )
    counts = await _member_counts(session)
    return _to_out(group, counts.get(group.id, 0))


@router.get("/{group_id}/members", response_model=list[RoleGroupMemberOut])
async def list_role_group_members(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[RoleGroupMemberOut]:
    """List the members of a custom role group.

    The built-in moderator group has no stored members (membership is derived
    from the user's role), so it cannot be listed here.
    """
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if group.builtin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The built-in moderator group has no stored members "
            "(membership comes from the user's role).",
        )
    rows = (
        await session.execute(
            select(RoleGroupMembership, User)
            .join(User, User.id == RoleGroupMembership.user_id)
            .where(RoleGroupMembership.role_group_id == group_id)
            .order_by(User.id)
        )
    ).all()
    out: list[RoleGroupMemberOut] = []
    for membership, user in rows:
        label = user.username or user.name or user.email or user.sub
        out.append(
            RoleGroupMemberOut(
                user_id=user.id,
                name=f"{label}#{user.id}",
                email=user.email,
                role=user.role,
                source=membership.source,
                enabled=user.enabled,
            )
        )
    return out


@router.delete(
    "/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_role_group_member(
    group_id: int,
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> None:
    """Temporarily remove a user from a role group.

    Cuts the user's access to that group's models immediately — useful when an
    account can't be disabled right away but its access must be revoked now. The
    removal is *temporary*: an ``auto`` membership is re-granted at the user's
    next login if a team mapping still matches. Not available for the built-in
    moderator group.
    """
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if group.builtin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot remove members from the built-in moderator group "
            "(it is derived from the user's role — change the role instead).",
        )
    membership = (
        await session.execute(
            select(RoleGroupMembership).where(
                RoleGroupMembership.role_group_id == group_id,
                RoleGroupMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User is not in this role group.")
    target = await session.get(User, user_id)
    await session.delete(membership)
    await record_audit(
        session,
        action=AuditAction.ROLE_GROUP_MEMBER_REMOVE,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="role_group",
        target_id=group_id,
        detail={
            "group": group.name,
            "user_id": user_id,
            "user": actor_display_name(target) if target is not None else str(user_id),
            "was_source": membership.source,
            "temporary": True,
        },
        ip=request.client.host if request.client else None,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role_group(
    group_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> None:
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if group.builtin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The built-in moderator group cannot be deleted.",
        )
    name = group.name
    await session.delete(group)
    await record_audit(
        session,
        action=AuditAction.ROLE_GROUP_DELETE,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="role_group",
        target_id=group_id,
        detail={"name": name},
        ip=request.client.host if request.client else None,
    )
