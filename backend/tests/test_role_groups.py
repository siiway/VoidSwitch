"""Tests for role groups: team mapping, model access, and login policy."""

from __future__ import annotations

import pytest
from voidswitch.core import auth
from voidswitch.core.config import get_settings
from voidswitch.models.db import (
    ModelEntry,
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
    assert role_groups.resolve_main_team_role("main", teams) is not None
    assert role_groups.resolve_main_team_role("main", teams).value == "admin"
    assert role_groups.resolve_main_team_role("other", teams) is None
    assert role_groups.resolve_main_team_role("", teams) is None


@pytest.mark.asyncio
async def test_evaluate_auto_group_ids(db):
    async with db.session() as session:
        group = RoleGroup(name="Beta", builtin=False)
        session.add(group)
        await session.flush()
        session.add(
            RoleGroupMapping(role_group_id=group.id, team_id="t-beta", min_role="admin")
        )
        await session.flush()
        gid = group.id

    async with db.session() as session:
        # admin in t-beta → granted; member in t-beta → not granted.
        granted = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "t-beta", "role": "admin"}]
        )
        assert granted == {gid}
        not_granted = await role_groups.evaluate_auto_group_ids(
            session, [{"id": "t-beta", "role": "member"}]
        )
        assert not_granted == set()


@pytest.mark.asyncio
async def test_user_can_access_model(db):
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        group = RoleGroup(name="Beta", builtin=False)
        session.add(group)
        await session.flush()
        gid = group.id
        session.add(ModelEntry(model_id="m-open", allowed_role_group_ids=[gid]))
        session.add(ModelEntry(model_id="m-locked", allowed_role_group_ids=[]))
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
        session.add(
            RoleGroupMapping(role_group_id=group.id, team_id="other", min_role="member")
        )
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
        session.add(
            RoleGroupMapping(role_group_id=group.id, team_id="t-x", min_role="member")
        )
        await session.flush()
        gid = group.id

    settings = _settings(main_team_id="main")
    identity = _identity("worker", teams=[{"id": "t-x", "role": "member"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.role == "member"
        ids = await role_groups.user_group_ids(session, user.id)
        assert ids == {gid}


@pytest.mark.asyncio
async def test_reenable_restores_tokens_on_login(db):
    settings = _settings(main_team_id="main")
    async with db.session() as session:
        user = User(sub="u-disabled", role="admin", enabled=True)
        session.add(user)
        await session.flush()
        token = VoidToken(
            user_id=user.id, name="t", token_hash="h" * 64, token_prefix="p"
        )
        session.add(token)
        await session.flush()
        # Simulate the disable flow: tokens off + flag set, account re-enabled.
        token.enabled = False
        user.void_tokens_admin_disabled = True
        user.enabled = True
        await session.flush()

    identity = _identity("u-disabled", teams=[{"id": "main", "role": "admin"}])
    async with db.session() as session:
        user = await auth.upsert_user(session, settings, identity)
        assert user.void_tokens_admin_disabled is False
        assert all(t.enabled for t in user.tokens)
