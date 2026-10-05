"""Cross-worker Redis rate limits and role-group budget resolution."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from voidswitch.core.ratelimit import LimitCandidate, RedisRateLimiter
from voidswitch.core.redis import RedisConfig, RedisService
from voidswitch.models.db import ExposedModel, RoleGroup, RoleGroupMembership, User
from voidswitch.services import role_groups


@pytest.fixture
async def redis_service():
    service = RedisService(
        RedisConfig(url="redis://localhost:6379/15", key_prefix=f"voidswitch:test:{uuid4().hex}")
    )
    await service.ping()
    try:
        yield service
    finally:
        keys = [key async for key in service.client.scan_iter(match=f"{service.prefix}:*")]
        if keys:
            await service.client.delete(*keys)
        await service.close()


async def test_sliding_window_is_shared_and_atomic(redis_service):
    first = RedisRateLimiter(redis_service)
    second = RedisRateLimiter(redis_service)

    decisions = await asyncio.gather(
        *(
            limiter.acquire("subject", window_seconds=60, max_requests=3)
            for limiter in [first, second] * 5
        )
    )

    assert decisions.count(True) == 3
    assert decisions.count(False) == 7


async def test_multi_group_reservation_is_atomic(redis_service):
    first = RedisRateLimiter(redis_service)
    second = RedisRateLimiter(redis_service)
    candidates = [LimitCandidate("tight", 60, 1), LimitCandidate("roomy", 60, 2)]

    decisions = await asyncio.gather(
        *(limiter.reserve_any(candidates) for limiter in [first, second] * 4)
    )

    assert decisions.count(True) == 3
    assert decisions.count(False) == 5


async def test_unlimited_candidate_does_not_create_counter(redis_service):
    limiter = RedisRateLimiter(redis_service)

    for _ in range(10):
        assert await limiter.reserve_any([LimitCandidate("free", 60, 0)])

    assert [
        key async for key in redis_service.client.scan_iter(match=f"{redis_service.prefix}:*")
    ] == []


async def test_rate_limit_groups_moderator(db):
    async with db.session() as session:
        mod_group = await role_groups.ensure_moderator_group(session)
        mod = User(sub="mod", role="admin")
        session.add(mod)
        entry = ExposedModel(model_id="m-x", allowed_role_group_ids=[])
        session.add(entry)
        await session.flush()

        groups = await role_groups.rate_limit_groups(session, mod, entry)
        assert [g.id for g in groups] == [mod_group.id]
        groups = await role_groups.rate_limit_groups(session, mod, None)
        assert [g.id for g in groups] == [mod_group.id]


async def test_rate_limit_groups_filtered_by_model_access(db):
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

        groups = await role_groups.rate_limit_groups(session, member, entry)
        assert [g.id for g in groups] == [g_open.id]
        groups = await role_groups.rate_limit_groups(session, member, None)
        assert {g.id for g in groups} == {g_open.id, g_other.id}
