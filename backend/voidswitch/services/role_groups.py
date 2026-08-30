"""Role groups ("身份组") — team-driven membership and per-model access control.

A *role group* gates which models a (non-moderator) user may call. Owner /
co-owner / admin are the platform **moderators**: they belong to the built-in
``moderator`` group implicitly (never stored) and may always call every model.

Membership of custom groups is recomputed at every login from
:class:`RoleGroupMapping` rules: "members of Prism team *T* whose effective role
is at least *R* get group *G*". The resolved set is persisted as
:class:`RoleGroupMembership` rows so the gateway can authorise calls without
re-contacting Prism on each request.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import (
    CALL_RATE_LIMIT_WINDOW_SECONDS,
    MODERATOR_CALL_RATE_LIMIT_MAX_REQUESTS,
    MODERATOR_GROUP_SLUG,
    TEAM_ROLE_RANK,
    Role,
)
from voidswitch.core.auth import STAFF_ROLES
from voidswitch.models.db import (
    ExposedModel,
    RoleGroup,
    RoleGroupAdminship,
    RoleGroupMembership,
    User,
)

# Normalised → canonical team role string (mirrors Prism's role vocabulary).
_TEAM_ROLE_ALIASES = {
    "owner": "owner",
    "coowner": "co-owner",
    "co_owner": "co-owner",
    "co-owner": "co-owner",
    "admin": "admin",
    "member": "member",
}

# Team role → VoidSwitch tier for the main-team moderator mapping.
_MAIN_TEAM_ROLE_TO_VS = {
    "owner": Role.OWNER,
    "co-owner": Role.CO_OWNER,
    "admin": Role.ADMIN,
}


def normalise_team_role(value: str | None) -> str | None:
    """Canonicalise a Prism team role string ("co_owner" → "co-owner")."""
    if not value:
        return None
    key = str(value).strip().lower().replace(" ", "")
    key = key.replace("-", "").replace("_", "")
    # _TEAM_ROLE_ALIASES is keyed by the collapsed form for owner/admin/member,
    # but co-owner needs its hyphen back — handle via TEAM_ROLE_RANK lookup.
    if key in ("coowner",):
        return "co-owner"
    return _TEAM_ROLE_ALIASES.get(key)


def team_role_rank(value: str | None) -> int:
    """Numeric rank of a (canonical or raw) team role; 0 when unknown."""
    canonical = normalise_team_role(value)
    if canonical is None:
        return 0
    return TEAM_ROLE_RANK.get(canonical, 0)


def effective_team_role(teams: Sequence[dict[str, Any]], team_id: str) -> str | None:
    """Highest effective role the user holds in ``team_id`` (None when absent)."""
    if not team_id:
        return None
    best_rank = 0
    best_role: str | None = None
    for entry in teams or []:
        if str(entry.get("id")) != str(team_id):
            continue
        role = normalise_team_role(entry.get("role"))
        rank = team_role_rank(role)
        if rank > best_rank:
            best_rank, best_role = rank, role
    return best_role


def resolve_main_team_role(main_team_id: str, teams: Sequence[dict[str, Any]]) -> Role | None:
    """Map the user's role in ``main_team_id`` onto a VoidSwitch moderator tier.

    Returns ``Role.OWNER`` / ``CO_OWNER`` / ``ADMIN`` when the user holds the
    corresponding role (or higher, for admin) in the main team, else ``None``.
    """
    if not main_team_id:
        return None
    role = effective_team_role(teams, main_team_id)
    if role is None:
        return None
    # Exact owner/co-owner; admin covers admin only (owner/co-owner already
    # matched above and outrank admin).
    return _MAIN_TEAM_ROLE_TO_VS.get(role)


def is_moderator(user: User) -> bool:
    """Owner / co-owner / admin are the built-in moderators."""
    return user.role in STAFF_ROLES


async def ensure_moderator_group(session: AsyncSession) -> RoleGroup:
    """Seed (idempotently) the built-in moderator role group."""
    group = (
        await session.execute(select(RoleGroup).where(RoleGroup.slug == MODERATOR_GROUP_SLUG))
    ).scalar_one_or_none()
    if group is None:
        group = RoleGroup(
            slug=MODERATOR_GROUP_SLUG,
            name="Moderator",
            description=(
                "Owner / co-owner / admin. Always allowed to call every model. "
                "Built-in — cannot be deleted or restricted."
            ),
            builtin=True,
            # Moderators get a higher default call budget than custom groups.
            call_rate_limit_window_seconds=CALL_RATE_LIMIT_WINDOW_SECONDS,
            call_rate_limit_max_requests=MODERATOR_CALL_RATE_LIMIT_MAX_REQUESTS,
        )
        session.add(group)
        await session.flush()
    return group


async def evaluate_auto_group_ids(
    session: AsyncSession, teams: Sequence[dict[str, Any]]
) -> tuple[set[int], set[int]]:
    """Groups granted by the team mappings for these team memberships.

    Returns a tuple ``(member_group_ids, admin_group_ids)``:

    * ``member_group_ids`` — groups the user gets model-access membership of
      (from ``grants="member"`` mappings).
    * ``admin_group_ids`` — groups the user gets read-only observer adminship
      of (from ``grants="admin"`` mappings).

    Adminship does NOT imply membership: a mapping with ``grants="admin"``
    grants only the observer capability. To grant both, an editor must add two
    mapping rows.

    The built-in moderator group is skipped: its "members" are staff (derived
    from the platform role) and it never accepts admin mappings.
    """
    groups = (
        (await session.execute(select(RoleGroup).where(RoleGroup.builtin.is_(False))))
        .scalars()
        .all()
    )
    granted_member: set[int] = set()
    granted_admin: set[int] = set()
    for group in groups:
        member_hit = False
        admin_hit = False
        for mapping in group.mappings:
            if member_hit and admin_hit:
                break
            user_rank = team_role_rank(effective_team_role(teams, mapping.team_id))
            if user_rank <= 0:
                continue
            if user_rank < team_role_rank(mapping.min_role):
                continue
            if mapping.grants == "admin":
                admin_hit = True
            else:
                # Default (and only other legal value) is "member".
                member_hit = True
        if member_hit:
            granted_member.add(group.id)
        if admin_hit:
            granted_admin.add(group.id)
    return granted_member, granted_admin


async def sync_auto_memberships(
    session: AsyncSession, user: User, auto_group_ids: Iterable[int]
) -> None:
    """Reconcile a user's ``source="auto"`` memberships with ``auto_group_ids``.

    Manual memberships are left untouched. Membership rows are queried directly
    (rather than via the relationship) so this works for a freshly-created user
    under an async session without triggering a lazy load.
    """
    desired = set(auto_group_ids)
    rows = (
        (
            await session.execute(
                select(RoleGroupMembership).where(RoleGroupMembership.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    existing = {m.role_group_id: m for m in rows}

    for gid, membership in existing.items():
        if membership.source == "auto" and gid not in desired:
            await session.delete(membership)

    for gid in desired:
        current = existing.get(gid)
        if current is None:
            session.add(RoleGroupMembership(user_id=user.id, role_group_id=gid, source="auto"))
        elif current.source != "manual":
            current.source = "auto"
    await session.flush()


async def sync_auto_adminships(
    session: AsyncSession, user: User, auto_admin_group_ids: Iterable[int]
) -> None:
    """Reconcile a user's ``source="auto"`` role-group adminships.

    Mirrors :func:`sync_auto_memberships`: rows granted from a ``grants="admin"``
    mapping are re-evaluated at every login, manual assignments (``source ==
    "manual"``) are left untouched. Kept as a separate table (rather than a
    flag on membership) so admin-without-member — the real cross-organisation
    case where an org's Prism admin needs the observer view but no model call
    quota — is expressible.
    """
    desired = set(auto_admin_group_ids)
    rows = (
        (
            await session.execute(
                select(RoleGroupAdminship).where(RoleGroupAdminship.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    existing = {a.role_group_id: a for a in rows}

    for gid, adminship in existing.items():
        if adminship.source == "auto" and gid not in desired:
            await session.delete(adminship)

    for gid in desired:
        current = existing.get(gid)
        if current is None:
            session.add(RoleGroupAdminship(user_id=user.id, role_group_id=gid, source="auto"))
        elif current.source != "manual":
            current.source = "auto"
    await session.flush()


async def user_group_ids(session: AsyncSession, user_id: int) -> set[int]:
    """All role-group ids a user currently belongs to (excludes moderator)."""
    rows = (
        (
            await session.execute(
                select(RoleGroupMembership.role_group_id).where(
                    RoleGroupMembership.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def rate_limit_groups(
    session: AsyncSession, user: User, entry: ExposedModel | None
) -> list[RoleGroup]:
    """The role groups whose call rate limits govern ``user``'s gateway call.

    Staff resolve to the built-in moderator group (they hold no stored
    memberships); everyone else resolves to their stored custom-group
    memberships. When ``entry`` (the exposed model being called) is given, only
    groups that actually grant access to it are returned — a group the user
    belongs to but that can't call the model contributes no budget. Pass
    ``entry=None`` to consider all of the user's groups (e.g. when the model
    isn't tracked by an ExposedModel row and no per-model access filter
    applies).

    A member of several groups may call as long as ANY returned group still has
    budget; the caller picks the group with the most remaining capacity.
    """
    if is_moderator(user):
        group = (
            await session.execute(select(RoleGroup).where(RoleGroup.slug == MODERATOR_GROUP_SLUG))
        ).scalar_one_or_none()
        # Moderator access is unconditional, so the moderator group always counts.
        return [group] if group is not None else []

    ids = await user_group_ids(session, user.id)
    if not ids:
        return []
    groups = list(
        (await session.execute(select(RoleGroup).where(RoleGroup.id.in_(ids)))).scalars().all()
    )
    if entry is not None:
        allowed = set(entry.allowed_role_group_ids or [])
        groups = [g for g in groups if g.id in allowed]
    return groups


async def user_can_access_model(session: AsyncSession, user: User, model_id: str) -> bool:
    """Whether ``user`` may call ``model_id`` (an exposed model id).

    Moderators may call everything. Everyone else needs one of their role groups
    listed in the model's ``allowed_role_group_ids`` (empty → moderators only).
    """
    if is_moderator(user):
        return True
    entry = (
        await session.execute(select(ExposedModel).where(ExposedModel.model_id == model_id))
    ).scalar_one_or_none()
    allowed = set(entry.allowed_role_group_ids or []) if entry is not None else set()
    if not allowed:
        return False
    return bool(allowed & await user_group_ids(session, user.id))


def model_allowed_for_groups(
    entry: ExposedModel | None, group_ids: set[int], *, is_mod: bool
) -> bool:
    """Pure-Python access check used when the caller already loaded the data."""
    if is_mod:
        return True
    allowed = set(entry.allowed_role_group_ids or []) if entry is not None else set()
    return bool(allowed & group_ids)
