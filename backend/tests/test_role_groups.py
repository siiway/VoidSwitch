"""Tests for role groups: team mapping, model access, and login policy."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from voidswitch.core import auth
from voidswitch.core.config import get_settings
from voidswitch.models.db import (
    ExposedModel,
    RoleGroup,
    RoleGroupMapping,
    User,
    VoidToken,
)
from voidswitch.services import role_groups


def _identity(sub: str, *, teams=None) -> auth.PrismIdentity:
    return auth.PrismIdentity(
        sub=sub,
        username=sub,
        email=f"{sub}@example.com",
        name=sub,
        picture=None,
        teams=teams or [],
    )


def _settings(main_team_id: str = ""):
    s = get_settings()
    # Mutate a copy-ish: these fields are plain attributes; restore after via fixture.
    s.admin.main_team_id = main_team_id
    s.admin.owner_subs = []
    s.admin.owner_emails = []
    s.admin.bootstrap_first_user = False
    return s


@pytest.fixture(autouse=True)
def _restore_settings():
    s = get_settings()
    saved = (
        s.admin.main_team_id,
        list(s.admin.owner_subs),
        list(s.admin.owner_emails),
        s.admin.bootstrap_first_user,
    )
    yield
    (
        s.admin.main_team_id,
        s.admin.owner_subs,
        s.admin.owner_emails,
        s.admin.bootstrap_first_user,
    ) = saved


def test_effective_team_role_and_rank():
    teams = [{"id": "t1", "role": "co_owner"}, {"id": "t2", "role": "member"}]
    assert role_groups.effective_team_role(teams, "t1") == "co-owner"
    assert role_groups.effective_team_role(teams, "t2") == "member"
    assert role_groups.effective_team_role(teams, "nope") is None
    assert role_groups.team_role_rank("owner") > role_groups.team_role_rank("admin")


def test_resolve_main_team_role():
    teams = [{"id": "main", "role": "admin"}]
    role = role_groups.resolve_main_team_role("main", teams)
    assert role is not None
    assert role.value == "admin"
    assert role_groups.resolve_main_team_role("other", teams) is None
    assert role_groups.resolve_main_team_role("", teams) is None


@pytest.mark.asyncio
async def test_evaluate_auto_group_ids(db):
    async with db.session() as session:
        group = RoleGroup(name="Beta", builtin=False)
        session.add(group)
        await session.flush()
        session.add(RoleGroupMapping(role_group_id=group.id, team_id="t-beta", min_role="admin"))
        await session.flush()
        gid = group.id

    async with db.session() as session:
        # admin in t-beta → granted membership; member in t-beta → not granted.
        # The evaluator now returns (member_group_ids, admin_group_ids); the
        # legacy mapping (no ``grants`` value / defaulting to "member") lands
        # entirely on the member side, and no admin mapping exists here so the
        # admin set is always empty.
        member_ids, admin_ids = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "t-beta", "role": "admin"}]
        )
        assert member_ids == {gid}
        assert admin_ids == set()
        member_ids, admin_ids = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "t-beta", "role": "member"}]
        )
        assert member_ids == set()
        assert admin_ids == set()


@pytest.mark.asyncio
async def test_user_can_access_model(db):
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        group = RoleGroup(name="Beta", builtin=False)
        session.add(group)
        await session.flush()
        gid = group.id
        session.add(ExposedModel(model_id="m-open", allowed_role_group_ids=[gid]))
        session.add(ExposedModel(model_id="m-locked", allowed_role_group_ids=[]))
        mod = User(sub="mod", role="admin")
        member_in = User(sub="memin", role="member")
        member_out = User(sub="memout", role="member")
        session.add_all([mod, member_in, member_out])
        await session.flush()
        from voidswitch.models.db import RoleGroupMembership

        session.add(RoleGroupMembership(user_id=member_in.id, role_group_id=gid))
        await session.flush()

        # Moderator: everything.
        assert await role_groups.user_can_access_model(session, mod, "m-open")
        assert await role_groups.user_can_access_model(session, mod, "m-locked")
        # Member in the group: only m-open.
        assert await role_groups.user_can_access_model(session, member_in, "m-open")
        assert not await role_groups.user_can_access_model(session, member_in, "m-locked")
        # Member without the group: neither.
        assert not await role_groups.user_can_access_model(session, member_out, "m-open")


@pytest.mark.asyncio
async def test_login_denied_without_access(db):
    settings = _settings(main_team_id="main")
    identity = _identity("nobody", teams=[{"id": "other", "role": "member"}])
    async with db.session() as session:
        with pytest.raises(auth.LoginDenied):
            await auth.upsert_user(session, settings, identity)


@pytest.mark.asyncio
async def test_login_grants_moderator_from_main_team(db):
    settings = _settings(main_team_id="main")
    identity = _identity("boss", teams=[{"id": "main", "role": "owner"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.role == "owner"


@pytest.mark.asyncio
async def test_admin_comes_from_main_team_role(db):
    """The admin tier is the main team's ``admin`` role — and it's snapshotted."""
    settings = _settings(main_team_id="main")
    identity = _identity("mod", teams=[{"id": "main", "role": "admin"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.role == "admin"
        # prism_role snapshots the *main-team* role (drives the override badge).
        assert user.prism_role == "admin"


@pytest.mark.asyncio
async def test_admin_in_other_team_is_not_platform_admin(db):
    """Being admin of a non-main team never confers the platform admin tier.

    (This is also the shape of a former "Prism instance admin": privileged
    elsewhere, but only a member here — with model access via a role group.)
    """
    settings = _settings(main_team_id="main")
    async with db.session() as session:
        group = RoleGroup(name="Mapped", builtin=False)
        session.add(group)
        await session.flush()
        session.add(RoleGroupMapping(role_group_id=group.id, team_id="other", min_role="member"))
        await session.flush()

    identity = _identity("outsider", teams=[{"id": "other", "role": "admin"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.role == "member"
        # Not in the main team → no main-team role recorded.
        assert user.prism_role is None


@pytest.mark.asyncio
async def test_login_grants_member_via_role_group(db):
    settings = _settings(main_team_id="main")
    async with db.session() as session:
        group = RoleGroup(name="Mapped", builtin=False)
        session.add(group)
        await session.flush()
        session.add(RoleGroupMapping(role_group_id=group.id, team_id="t-x", min_role="member"))
        await session.flush()
        gid = group.id

    settings = _settings(main_team_id="main")
    identity = _identity(
        "worker", teams=[{"id": "t-x", "role": "member"}, {"id": "t-y", "role": "member"}]
    )
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.role == "member"
        ids = await role_groups.user_group_ids(session, user.id)
        assert ids == {gid}
        # The user's Prism team ids are snapshotted for the dashboard's "team
        # role" display (a non-main-team member is labelled by role group, with
        # their team ids on hover).
        assert user.team_ids == ["t-x", "t-y"]


@pytest.mark.asyncio
async def test_reenable_restores_tokens_on_login(db):
    settings = _settings(main_team_id="main")
    async with db.session() as session:
        user = User(sub="u-disabled", role="admin", enabled=True)
        session.add(user)
        await session.flush()
        token = VoidToken(user_id=user.id, name="t", token_hash="h" * 64, token_prefix="p")
        session.add(token)
        await session.flush()
        # Simulate the disable flow: the parked token is marked auto_disabled and
        # the flag set, account re-enabled.
        token.enabled = False
        token.auto_disabled = True
        user.void_tokens_admin_disabled = True
        user.enabled = True
        await session.flush()

    identity = _identity("u-disabled", teams=[{"id": "main", "role": "admin"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.void_tokens_admin_disabled is False
        assert all(t.enabled for t in user.tokens)


# --------------------------------------------------------------------------- #
# Rate-limit administration (dashboard API)
# --------------------------------------------------------------------------- #


def _owner_headers() -> dict[str, str]:
    from voidswitch.core.config import get_settings
    from voidswitch.core.security import create_session_token

    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject="user-1",
        extra={"role": "owner", "name": "alice", "epoch": 0},
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_owner(db) -> None:
    async with db.session() as session:
        existing = (
            await session.execute(select(User).where(User.sub == "user-1"))
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(sub="user-1", username="alice", role="owner"))
            await session.flush()


@pytest.mark.asyncio
async def test_create_group_with_custom_rate_limit(client, db):
    await _seed_owner(db)
    resp = await client.post(
        "/api/admin/role-groups",
        headers=_owner_headers(),
        json={
            "name": "Limited",
            "call_rate_limit_window_seconds": 60,
            "call_rate_limit_max_requests": 5,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["call_rate_limit_window_seconds"] == 60
    assert body["call_rate_limit_max_requests"] == 5


@pytest.mark.asyncio
async def test_create_group_defaults_to_30_per_30s(client, db):
    await _seed_owner(db)
    resp = await client.post(
        "/api/admin/role-groups", headers=_owner_headers(), json={"name": "Defaults"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["call_rate_limit_window_seconds"] == 30
    assert body["call_rate_limit_max_requests"] == 30


@pytest.mark.asyncio
async def test_moderator_group_limit_editable_but_identity_locked(client, db):
    await _seed_owner(db)
    async with db.session() as session:
        group = await role_groups.ensure_moderator_group(session)
        gid = group.id
        # Seeded with the moderator default (50 per 30s).
        assert group.call_rate_limit_max_requests == 50

    headers = _owner_headers()
    # Rate limit edits are allowed on the built-in group.
    resp = await client.patch(
        f"/api/admin/role-groups/{gid}",
        headers=headers,
        json={"call_rate_limit_max_requests": 80},
    )
    assert resp.status_code == 200
    assert resp.json()["call_rate_limit_max_requests"] == 80
    # Everything else is locked.
    resp = await client.patch(
        f"/api/admin/role-groups/{gid}", headers=headers, json={"name": "Renamed"}
    )
    assert resp.status_code == 400
    # Owner's gateway budget follows the edited moderator limit.
    async with db.session() as session:
        group = await session.get(RoleGroup, gid)
        assert group is not None
        assert group.call_rate_limit_max_requests == 80


@pytest.mark.asyncio
async def test_negative_rate_limit_rejected(client, db):
    await _seed_owner(db)
    resp = await client.post(
        "/api/admin/role-groups",
        headers=_owner_headers(),
        json={"name": "Bad", "call_rate_limit_max_requests": -1},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Adminship (grants="admin" mappings + RoleGroupAdminship syncing)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_evaluate_auto_group_ids_splits_member_and_admin(db):
    """A mixed mapping set separates its ``grants="member"`` and
    ``grants="admin"`` hits into two disjoint id sets."""
    async with db.session() as session:
        group_m = RoleGroup(name="MemberOnly", builtin=False)
        group_a = RoleGroup(name="AdminOnly", builtin=False)
        group_both = RoleGroup(name="Both", builtin=False)
        session.add_all([group_m, group_a, group_both])
        await session.flush()
        session.add(
            RoleGroupMapping(
                role_group_id=group_m.id,
                team_id="team-a",
                min_role="member",
                grants="member",
            )
        )
        session.add(
            RoleGroupMapping(
                role_group_id=group_a.id,
                team_id="team-a",
                min_role="admin",
                grants="admin",
            )
        )
        # Same team+min_role, both flavours → single evaluator pass hits both.
        session.add(
            RoleGroupMapping(
                role_group_id=group_both.id,
                team_id="team-a",
                min_role="admin",
                grants="member",
            )
        )
        session.add(
            RoleGroupMapping(
                role_group_id=group_both.id,
                team_id="team-a",
                min_role="admin",
                grants="admin",
            )
        )
        await session.flush()
        ids = (group_m.id, group_a.id, group_both.id)

    async with db.session() as session:
        # Team admin: satisfies member+admin cutoffs.
        member_ids, admin_ids = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "team-a", "role": "admin"}]
        )
        assert ids[0] in member_ids  # MemberOnly
        assert ids[2] in member_ids  # Both (member half)
        assert ids[1] not in member_ids  # AdminOnly stays out
        assert ids[1] in admin_ids
        assert ids[2] in admin_ids
        assert ids[0] not in admin_ids

        # Team member: below AdminOnly's cutoff, above MemberOnly's only.
        member_ids, admin_ids = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "team-a", "role": "member"}]
        )
        assert member_ids == {ids[0]}
        assert admin_ids == set()


@pytest.mark.asyncio
async def test_sync_auto_adminships_is_idempotent_and_keeps_manual(db):
    """``sync_auto_adminships`` mirrors ``sync_auto_memberships``: auto rows
    are reconciled on each call, manual rows persist untouched."""
    from voidswitch.models.db import RoleGroupAdminship

    async with db.session() as session:
        u = User(sub="admin-obs", role="member")
        g1 = RoleGroup(name="G1", builtin=False)
        g2 = RoleGroup(name="G2", builtin=False)
        session.add_all([u, g1, g2])
        await session.flush()
        # Seed a manual adminship for g2 that must never be reaped.
        session.add(RoleGroupAdminship(user_id=u.id, role_group_id=g2.id, source="manual"))
        await session.flush()
        uid, gid1, gid2 = u.id, g1.id, g2.id

    async with db.session() as session:
        user = await session.get(User, uid)
        assert user is not None
        await role_groups.sync_auto_adminships(session, user, [gid1])
        rows = (
            (
                await session.execute(
                    select(RoleGroupAdminship).where(RoleGroupAdminship.user_id == uid)
                )
            )
            .scalars()
            .all()
        )
        by_gid = {r.role_group_id: r for r in rows}
        assert set(by_gid.keys()) == {gid1, gid2}
        assert by_gid[gid1].source == "auto"
        assert by_gid[gid2].source == "manual"

    # Second sync with an empty desired set: g1 (auto) drops, g2 (manual) stays.
    async with db.session() as session:
        user = await session.get(User, uid)
        assert user is not None
        await role_groups.sync_auto_adminships(session, user, [])
        remaining = (
            (
                await session.execute(
                    select(RoleGroupAdminship).where(RoleGroupAdminship.user_id == uid)
                )
            )
            .scalars()
            .all()
        )
        assert {r.role_group_id for r in remaining} == {gid2}
        assert remaining[0].source == "manual"


@pytest.mark.asyncio
async def test_login_permitted_by_admin_mapping_only(db):
    """A user whose only reason to be here is an ``admin`` mapping passes the
    access policy — the observer-only case is a first-class login reason."""
    from voidswitch.models.db import RoleGroupAdminship

    async with db.session() as session:
        group = RoleGroup(name="OrgA", builtin=False)
        session.add(group)
        await session.flush()
        session.add(
            RoleGroupMapping(
                role_group_id=group.id,
                team_id="org-a",
                min_role="admin",
                grants="admin",
            )
        )
        await session.flush()

    settings = _settings()
    identity = _identity("observer", teams=[{"id": "org-a", "role": "admin"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        # Not staff — the platform role falls through to member (no main team).
        assert user.role == "member"
        # Adminship was synced.
        adminships = (
            (
                await session.execute(
                    select(RoleGroupAdminship).where(RoleGroupAdminship.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(adminships) == 1
        # No membership was granted for the same mapping.
        assert user.group_memberships == []


# --------------------------------------------------------------------------- #
# Write-permission tightening (admin can read, owner-only for edits)
# --------------------------------------------------------------------------- #


def _staff_admin_headers() -> dict[str, str]:
    """Session headers for a platform admin (staff but not owner)."""
    from voidswitch.core.config import get_settings
    from voidswitch.core.security import create_session_token

    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject="user-admin",
        extra={"role": "admin", "name": "admin", "epoch": 0},
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_staff_admin(db) -> None:
    async with db.session() as session:
        existing = (
            await session.execute(select(User).where(User.sub == "user-admin"))
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(sub="user-admin", username="admin", role="admin"))
            await session.flush()


@pytest.mark.asyncio
async def test_admin_cannot_create_or_edit_role_group(client, db):
    """Platform admin (staff-not-owner) may read but not mutate role groups."""
    await _seed_staff_admin(db)
    headers = _staff_admin_headers()
    # GET is allowed.
    resp = await client.get("/api/admin/role-groups", headers=headers)
    assert resp.status_code == 200
    # POST is forbidden.
    resp = await client.post("/api/admin/role-groups", headers=headers, json={"name": "NopeGroup"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_builtin_moderator_rejects_admin_mapping(client, db):
    """Even an owner cannot add ``grants='admin'`` to the built-in group."""
    await _seed_owner(db)
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        mod = (
            await session.execute(select(RoleGroup).where(RoleGroup.slug == "moderator"))
        ).scalar_one()
        mod_id = mod.id
    resp = await client.patch(
        f"/api/admin/role-groups/{mod_id}",
        headers=_owner_headers(),
        json={"mappings": [{"team_id": "team-x", "min_role": "admin", "grants": "admin"}]},
    )
    # The endpoint refuses moderator-group mapping edits altogether (existing
    # behaviour) with 400; the ``grants="admin"`` guard is a second wall for
    # any future path that would let a mapping edit through — either 400 or
    # 422 is a correct rejection.
    assert resp.status_code in (400, 422)
