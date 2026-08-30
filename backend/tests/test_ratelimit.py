"""Abuse rate limiting: the sliding-window limiter and per-role-group call limits."""

from __future__ import annotations

import pytest
from voidswitch.core import ratelimit
from voidswitch.core.ratelimit import SlidingWindowLimiter
from voidswitch.models.db import (
    ExposedModel,
    RoleGroup,
    RoleGroupMembership,
    User,
)
from voidswitch.services import role_groups


def test_sliding_window_disabled_allows_everything():
    lim = SlidingWindowLimiter()
    for _ in range(100):
        assert lim.allow("k", window_seconds=10, max_requests=0) is True


def test_sliding_window_enforces_max():
    lim = SlidingWindowLimiter()
    assert lim.allow("k", window_seconds=100, max_requests=2) is True
    assert lim.allow("k", window_seconds=100, max_requests=2) is True
    # Third within the window is blocked.
    assert lim.allow("k", window_seconds=100, max_requests=2) is False
    # A different key has its own budget.
    assert lim.allow("other", window_seconds=100, max_requests=2) is True


def test_sliding_window_remaining_peeks_without_recording():
    lim = SlidingWindowLimiter()
    assert lim.remaining("k", window_seconds=100, max_requests=3) == 3
    assert lim.allow("k", window_seconds=100, max_requests=3) is True
    assert lim.remaining("k", window_seconds=100, max_requests=3) == 2
    assert lim.remaining("k", window_seconds=100, max_requests=3) == 2  # peek is pure
    # Disabled → always reports budget.
    assert lim.remaining("k", window_seconds=100, max_requests=0) == 1


async def test_rate_limit_groups_moderator(db):
    """Staff resolve to the built-in moderator group, regardless of the model."""
    async with db.session() as session:
        mod_group = await role_groups.ensure_moderator_group(session)
        mod = User(sub="mod", role="admin")
        session.add(mod)
        entry = ExposedModel(model_id="m-x", allowed_role_group_ids=[])
        session.add(entry)
        await session.flush()

        groups = await role_groups.rate_limit_groups(session, mod, entry)
        assert [g.id for g in groups] == [mod_group.id]
        # Passthrough (entry=None) is identical for staff.
        groups = await role_groups.rate_limit_groups(session, mod, None)
        assert [g.id for g in groups] == [mod_group.id]


async def test_rate_limit_groups_filtered_by_model_access(db):
    """A member's groups only count when they actually grant the model."""
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        g_open = RoleGroup(name="Open", builtin=False)
        g_other = RoleGroup(name="Other", builtin=False)
        session.add_all([g_open, g_other])
        await session.flush()
        member = User(sub="mem", role="member")
        session.add(member)
        await session.flush()
        session.add_all(
            [
                RoleGroupMembership(user_id=member.id, role_group_id=g_open.id),
                RoleGroupMembership(user_id=member.id, role_group_id=g_other.id),
            ]
        )
        entry = ExposedModel(model_id="m-open", allowed_role_group_ids=[g_open.id])
        session.add(entry)
        await session.flush()

        # Only the group that grants m-open governs the call.
        groups = await role_groups.rate_limit_groups(session, member, entry)
        assert [g.id for g in groups] == [g_open.id]
        # Passthrough (entry=None): all of the user's groups count.
        groups = await role_groups.rate_limit_groups(session, member, None)
        assert {g.id for g in groups} == {g_open.id, g_other.id}


async def test_call_limit_passes_when_any_group_has_budget(db, monkeypatch):
    """A member of several groups passes while ANY group still has budget."""
    from voidswitch.api import proxy

    monkeypatch.setattr(ratelimit, "call_limiter", SlidingWindowLimiter())
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        g_tight = RoleGroup(
            name="Tight",
            builtin=False,
            call_rate_limit_window_seconds=30,
            call_rate_limit_max_requests=1,
        )
        g_roomy = RoleGroup(
            name="Roomy",
            builtin=False,
            call_rate_limit_window_seconds=30,
            call_rate_limit_max_requests=2,
        )
        session.add_all([g_tight, g_roomy])
        await session.flush()
        member = User(sub="mem2", role="member")
        session.add(member)
        await session.flush()
        session.add_all(
            [
                RoleGroupMembership(user_id=member.id, role_group_id=g_tight.id),
                RoleGroupMembership(user_id=member.id, role_group_id=g_roomy.id),
            ]
        )
        entry = ExposedModel(model_id="m-both", allowed_role_group_ids=[g_tight.id, g_roomy.id])
        session.add(entry)
        await session.flush()

        # 1 (tight) + 2 (roomy) = 3 calls pass; the 4th is refused.
        for _ in range(3):
            await proxy._check_call_rate_limit(session, member, "m-both")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await proxy._check_call_rate_limit(session, member, "m-both")
        assert exc.value.status_code == 429


async def test_call_limit_unlimited_group_never_throttles(db, monkeypatch):
    """A group with max=0 imposes no limit at all."""
    from voidswitch.api import proxy

    monkeypatch.setattr(ratelimit, "call_limiter", SlidingWindowLimiter())
    async with db.session() as session:
        await role_groups.ensure_moderator_group(session)
        g = RoleGroup(
            name="Free",
            builtin=False,
            call_rate_limit_window_seconds=30,
            call_rate_limit_max_requests=0,
        )
        session.add(g)
        await session.flush()
        member = User(sub="mem3", role="member")
        session.add(member)
        await session.flush()
        session.add(RoleGroupMembership(user_id=member.id, role_group_id=g.id))
        entry = ExposedModel(model_id="m-free", allowed_role_group_ids=[g.id])
        session.add(entry)
        await session.flush()

        for _ in range(50):
            await proxy._check_call_rate_limit(session, member, "m-free")
