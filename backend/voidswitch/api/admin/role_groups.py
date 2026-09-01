"""Role groups ("身份组") and their team→role auto-mappings.

A role group has two orthogonal capabilities:

* **Membership** — grants model call access (via ``ExposedModel.allowed_role_
  group_ids``).
* **Adminship** — grants a read-only observer view over the group's users,
  statistics, and logs (see ``RoleGroupAdminship``). *Never* grants model
  access on its own.

Both are auto-assigned at login from the group's mappings; each mapping row
carries a ``grants`` field (``"member"`` or ``"admin"``) that decides which
capability it hands out. To grant both from the same team+role condition an
editor must add two mappings.

The built-in ``moderator`` group is derived from the user's platform role and
never accepts ``grants="admin"`` mappings (see ``PATCH`` for the guard).

**Write access is owner-only.** Staff (admin) may *view* the list and members
but only owner / co-owner may create, edit, delete, or temporarily remove
members — this keeps a platform admin from silently reshaping the observer /
member landscape of tenant groups without owner approval.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import (
    CALL_RATE_LIMIT_MAX_REQUESTS,
    CALL_RATE_LIMIT_WINDOW_SECONDS,
    TEAM_ROLE_RANK,
)
from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    is_staff,
    managed_group_ids,
    require_owner,
    require_staff,
    require_staff_or_role_group_admin,
)
from voidswitch.core.database import get_session
from voidswitch.models.db import (
    RequestLog,
    RoleGroup,
    RoleGroupAdminship,
    RoleGroupMapping,
    RoleGroupMembership,
    User,
    VoidToken,
)
from voidswitch.models.schemas import (
    GroupStatsOut,
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

# Legal values for a mapping's ``grants`` field. "member" is the historical
# default (model access); "admin" grants read-only observer adminship.
_VALID_GRANTS = {"member", "admin"}


def _validated_min_role(value: str) -> str:
    canonical = normalise_team_role(value)
    if canonical is None or canonical not in TEAM_ROLE_RANK:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid team role '{value}'. Use owner / co-owner / admin / member.",
        )
    return canonical


def _validated_grants(value: str) -> str:
    v = (value or "member").strip().lower()
    if v not in _VALID_GRANTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid grants '{value}'. Use member or admin.",
        )
    return v


async def _member_counts(session: AsyncSession) -> dict[int, int]:
    rows = (
        await session.execute(
            select(RoleGroupMembership.role_group_id, func.count(RoleGroupMembership.id)).group_by(
                RoleGroupMembership.role_group_id
            )
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
        call_rate_limit_window_seconds=group.call_rate_limit_window_seconds,
        call_rate_limit_max_requests=group.call_rate_limit_max_requests,
        mappings=[
            RoleGroupMappingOut(id=m.id, team_id=m.team_id, min_role=m.min_role, grants=m.grants)
            for m in sorted(group.mappings, key=lambda m: m.id)
        ],
        member_count=member_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _validated_rate_limit(window: int, max_requests: int) -> tuple[int, int]:
    """Validate a per-group call rate limit pair (each >= 0; 0 = unlimited)."""
    if window < 0 or max_requests < 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rate limit window/max cannot be negative.",
        )
    return window, max_requests


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
    actor: User = Depends(require_owner),
) -> RoleGroupOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name is required.")
    clash = (
        await session.execute(select(RoleGroup).where(RoleGroup.name == name))
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role group with this name already exists.")
    window, max_requests = _validated_rate_limit(
        body.call_rate_limit_window_seconds
        if body.call_rate_limit_window_seconds is not None
        else CALL_RATE_LIMIT_WINDOW_SECONDS,
        body.call_rate_limit_max_requests
        if body.call_rate_limit_max_requests is not None
        else CALL_RATE_LIMIT_MAX_REQUESTS,
    )
    group = RoleGroup(
        name=name,
        description=(body.description or None),
        builtin=False,
        call_rate_limit_window_seconds=window,
        call_rate_limit_max_requests=max_requests,
    )
    session.add(group)
    await session.flush()
    seen: set[tuple[str, str, str]] = set()
    for m in body.mappings:
        team_id = m.team_id.strip()
        if not team_id:
            continue
        min_role = _validated_min_role(m.min_role)
        grants = _validated_grants(m.grants)
        key = (team_id, min_role, grants)
        if key in seen:
            # The table's unique constraint would 500 on a duplicate row later;
            # collapse the batch quietly and keep the first hit.
            continue
        seen.add(key)
        session.add(
            RoleGroupMapping(
                role_group_id=group.id,
                team_id=team_id,
                min_role=min_role,
                grants=grants,
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
        detail={
            "name": name,
            "mappings": [m.model_dump() for m in body.mappings],
            "call_rate_limit_window_seconds": window,
            "call_rate_limit_max_requests": max_requests,
        },
        ip=request.client.host if request.client else None,
    )
    return _to_out(group, 0)


@router.patch("/{group_id}", response_model=RoleGroupOut)
async def update_role_group(
    group_id: int,
    body: RoleGroupUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
) -> RoleGroupOut:
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    # The built-in moderator group is locked except for its call rate limit: its
    # name/description/membership are derived from staff roles and must never be
    # renamed or deleted, but its throttle is an operator knob.
    if group.builtin and (
        body.name is not None or body.description is not None or body.mappings is not None
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The built-in moderator group cannot be edited "
            "(only its call rate limit can be changed).",
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
        # Guard: the built-in moderator group never accepts admin mappings. Its
        # "admins" are the platform owners (a separate concept); allowing
        # grants="admin" here would create an ill-defined super-observer role
        # over all staff activity. The identity check on ``body.mappings ==
        # None`` above already rejects any edit to the moderator group's
        # mappings — this branch is dead for builtin groups — but keep the
        # explicit check in case a future refactor moves the ordering around.
        if group.builtin and any(
            (m.grants or "member").strip().lower() == "admin" for m in body.mappings
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "The built-in moderator group cannot accept 'admin' mappings.",
            )
        for existing in list(group.mappings):
            await session.delete(existing)
        await session.flush()
        new_mappings: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for m in body.mappings:
            team_id = m.team_id.strip()
            if not team_id:
                continue
            min_role = _validated_min_role(m.min_role)
            grants = _validated_grants(m.grants)
            # De-duplicate: the table enforces uniqueness of
            # (role_group_id, team_id, min_role, grants), so a duplicate entry
            # in the batch would 500 on flush.
            if (team_id, min_role, grants) in seen:
                continue
            seen.add((team_id, min_role, grants))
            session.add(
                RoleGroupMapping(
                    role_group_id=group.id,
                    team_id=team_id,
                    min_role=min_role,
                    grants=grants,
                )
            )
            new_mappings.append({"team_id": team_id, "min_role": min_role, "grants": grants})
        changes["mappings"] = new_mappings

    # Per-group call rate limit (the only editable knob on the built-in group).
    if body.call_rate_limit_window_seconds is not None or (
        body.call_rate_limit_max_requests is not None
    ):
        window, max_requests = _validated_rate_limit(
            body.call_rate_limit_window_seconds
            if body.call_rate_limit_window_seconds is not None
            else group.call_rate_limit_window_seconds,
            body.call_rate_limit_max_requests
            if body.call_rate_limit_max_requests is not None
            else group.call_rate_limit_max_requests,
        )
        if window != group.call_rate_limit_window_seconds:
            group.call_rate_limit_window_seconds = window
            changes["call_rate_limit_window_seconds"] = window
        if max_requests != group.call_rate_limit_max_requests:
            group.call_rate_limit_max_requests = max_requests
            changes["call_rate_limit_max_requests"] = max_requests

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


def _since_24h(session: AsyncSession) -> ColumnElement:
    """Database-native "24 hours ago" expression, dialect-aware.

    Mirrors ``admin/stats.py:_since_24h`` — kept local rather than shared so the
    two endpoints stay decoupled (one might grow a different window later).
    """
    from sqlalchemy import text

    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect == "postgresql":
        return func.now() - text("INTERVAL '24 hours'")
    return func.datetime("now", "-24 hours")


@router.get("/stats", response_model=GroupStatsOut)
async def role_group_stats(
    group_ids: list[int] | None = Query(
        default=None,
        description=(
            "Role-group ids to aggregate over. Omit to use the caller's managed "
            "groups (staff callers must pass an explicit set)."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    caller: User = Depends(require_staff_or_role_group_admin),
) -> GroupStatsOut:
    """Aggregated stats for a role-group admin's dashboard card.

    Scoped to the union of members of the requested groups (deduplicated across
    groups). A role-group admin caller may only request groups they administer;
    ``group_ids=`` omitted means "all groups I administer". Staff may request
    any subset; omitting is rejected for them (they should use the platform-wide
    ``/api/admin/stats`` instead — this endpoint is deliberately scoped).

    Fields intentionally omitted from the platform stats: providers, keys,
    proxies — those are not per-group concerns.
    """
    caller_managed = managed_group_ids(caller)
    if group_ids is None:
        if is_staff(caller) and not caller_managed:
            # Staff without any adminship must be explicit — refuse the sugar
            # of "all groups" (which would degenerate to "everyone") and point
            # them at the platform-wide endpoint.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Staff callers must pass an explicit group_ids= (or use "
                "/api/admin/stats for the platform-wide view).",
            )
        effective_ids = sorted(caller_managed)
    else:
        effective_ids = sorted(set(group_ids))
        if not is_staff(caller):
            outside = [g for g in effective_ids if g not in caller_managed]
            if outside:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"Not an admin of role group(s): {outside}",
                )

    # Resolve group names for the response label. Empty scope → empty result.
    groups = (
        (
            (
                await session.execute(
                    select(RoleGroup).where(RoleGroup.id.in_(effective_ids)).order_by(RoleGroup.id)
                )
            )
            .scalars()
            .all()
        )
        if effective_ids
        else []
    )
    if effective_ids and len(groups) != len(effective_ids):
        found_ids = {g.id for g in groups}
        missing = [gid for gid in effective_ids if gid not in found_ids]
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role group(s) not found: {missing}")

    if not effective_ids:
        return GroupStatsOut(
            group_ids=[],
            group_names=[],
            users=0,
            tokens=0,
            requests_24h=0,
            success_24h=0,
            failures_24h=0,
            tokens_24h=0,
        )

    # Union of user ids across the requested groups (dedup so a cross-group
    # member is counted once). Kept as a subquery so downstream aggregates can
    # join / filter without re-fetching the id set.
    member_user_id_subq = (
        select(RoleGroupMembership.user_id)
        .where(RoleGroupMembership.role_group_id.in_(effective_ids))
        .distinct()
    ).subquery()
    users_count = int(
        (await session.execute(select(func.count()).select_from(member_user_id_subq))).scalar_one()
        or 0
    )

    # user_sub union for request-log filtering — request logs key on user_sub,
    # not user_id, so we translate once here.
    subs_rows = (
        await session.execute(
            select(User.sub).where(
                User.id.in_(
                    select(RoleGroupMembership.user_id).where(
                        RoleGroupMembership.role_group_id.in_(effective_ids)
                    )
                )
            )
        )
    ).all()
    visible_subs = [s for (s,) in subs_rows if s]

    tokens_count = int(
        (
            await session.execute(
                select(func.count(VoidToken.id)).where(
                    VoidToken.deleted.is_(False),
                    VoidToken.user_id.in_(
                        select(RoleGroupMembership.user_id).where(
                            RoleGroupMembership.role_group_id.in_(effective_ids)
                        )
                    ),
                )
            )
        ).scalar_one()
        or 0
    )

    since = _since_24h(session)
    if visible_subs:
        base = select(RequestLog).where(
            RequestLog.ts >= since, RequestLog.user_sub.in_(visible_subs)
        )
    else:
        # No visible users → the aggregates are trivially zero; skip the query.
        return GroupStatsOut(
            group_ids=effective_ids,
            group_names=[g.name for g in groups],
            users=users_count,
            tokens=tokens_count,
            requests_24h=0,
            success_24h=0,
            failures_24h=0,
            tokens_24h=0,
        )

    requests_24h = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one() or 0
    )
    success_24h = int(
        (
            await session.execute(
                select(func.count()).select_from(
                    base.where(RequestLog.success.is_(True)).subquery()
                )
            )
        ).scalar_one()
        or 0
    )
    tokens_24h = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(RequestLog.total_tokens), 0)).where(
                    RequestLog.ts >= since,
                    RequestLog.user_sub.in_(visible_subs),
                )
            )
        ).scalar_one()
        or 0
    )
    avg_first_token_ms_24h = (
        await session.execute(
            select(func.avg(RequestLog.first_token_ms)).where(
                RequestLog.ts >= since,
                RequestLog.user_sub.in_(visible_subs),
                RequestLog.success.is_(True),
                RequestLog.stream.is_(True),
                RequestLog.first_token_ms.isnot(None),
            )
        )
    ).scalar_one()

    return GroupStatsOut(
        group_ids=effective_ids,
        group_names=[g.name for g in groups],
        users=users_count,
        tokens=tokens_count,
        requests_24h=requests_24h,
        success_24h=success_24h,
        failures_24h=requests_24h - success_24h,
        tokens_24h=tokens_24h,
        success_rate_24h=(round(success_24h / requests_24h * 100, 1) if requests_24h else 0.0),
        avg_first_token_ms_24h=(
            round(avg_first_token_ms_24h, 1) if avg_first_token_ms_24h is not None else None
        ),
        avg_tokens_per_request_24h=(round(tokens_24h / requests_24h, 1) if requests_24h else 0.0),
    )


@router.get("/{group_id}/members", response_model=list[RoleGroupMemberOut])
async def list_role_group_members(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    caller: User = Depends(require_staff_or_role_group_admin),
) -> list[RoleGroupMemberOut]:
    """List the members (and admins) of a custom role group.

    The result is a union of two rows-per-user views: users who *belong to* the
    group (a :class:`RoleGroupMembership` row) and users who *administer* it
    (a :class:`RoleGroupAdminship` row). The admin-only case is included so the
    dashboard can render "who is a group admin" from the same table — flagged
    with ``is_admin=true``.

    Reachable by staff (any group) or a role-group admin (only the groups they
    administer). The built-in moderator group has no stored members / admins.
    """
    group = await session.get(RoleGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if not is_staff(caller) and group_id not in managed_group_ids(caller):
        # Don't leak the group's existence to a non-authorised caller.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role group not found.")
    if group.builtin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The built-in moderator group has no stored members "
            "(membership comes from the user's role).",
        )
    member_rows = (
        await session.execute(
            select(RoleGroupMembership, User)
            .join(User, User.id == RoleGroupMembership.user_id)
            .where(RoleGroupMembership.role_group_id == group_id)
        )
    ).all()
    admin_rows = (
        await session.execute(
            select(RoleGroupAdminship, User)
            .join(User, User.id == RoleGroupAdminship.user_id)
            .where(RoleGroupAdminship.role_group_id == group_id)
        )
    ).all()
    admin_user_ids = {u.id for _, u in admin_rows}
    combined: dict[int, tuple[User, str, bool]] = {}
    for membership, user in member_rows:
        combined[user.id] = (user, membership.source, user.id in admin_user_ids)
    # Admin-only users (no membership row) still appear in the list.
    for adminship, user in admin_rows:
        if user.id in combined:
            continue
        combined[user.id] = (user, adminship.source, True)
    out: list[RoleGroupMemberOut] = []
    for user_id in sorted(combined):
        user, source, is_admin = combined[user_id]
        label = user.username or user.name or user.email or user.sub
        out.append(
            RoleGroupMemberOut(
                user_id=user.id,
                name=f"{label}#{user.id}",
                email=user.email,
                role=user.role,
                source=source,
                enabled=user.enabled,
                is_admin=is_admin,
            )
        )
    return out


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role_group_member(
    group_id: int,
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
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
    actor: User = Depends(require_owner),
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
