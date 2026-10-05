"""Focused integration tests for Redis-backed cross-worker coordination."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from voidswitch.core import sse
from voidswitch.core.redis import RedisConfig, RedisService
from voidswitch.services import settings_store
from voidswitch.tasks.manager import PeriodicTask, TaskManager


async def _peer(redis_backend) -> RedisService:
    service = RedisService(
        RedisConfig(
            url="redis://localhost:6379/15",
            key_prefix=f":{redis_backend.prefix}:",
            max_connections=3,
            connect_timeout=1.25,
            socket_timeout=1.5,
        )
    )
    await service.ping()
    return service


async def test_redis_config_namespaces_peer_clients(redis_backend):
    peer = await _peer(redis_backend)
    try:
        assert peer.prefix == redis_backend.prefix
        assert peer.key("rate", 42) == f"{redis_backend.prefix}:rate:42"
        kwargs = peer.client.connection_pool.connection_kwargs
        assert peer.client.connection_pool.max_connections == 3
        assert kwargs["socket_connect_timeout"] == 1.25
        assert kwargs["socket_timeout"] == 1.5
        assert kwargs["decode_responses"] is True
    finally:
        await peer.close()


async def test_lease_renews_and_only_owner_can_release(redis_backend):
    peer = await _peer(redis_backend)
    key = redis_backend.key("lease", "shared-job")
    try:
        async with redis_backend.lease("shared-job", 0.06) as acquired:
            assert acquired
            await asyncio.sleep(0.14)
            async with peer.lease("shared-job", 0.06) as peer_acquired:
                assert not peer_acquired

            await redis_backend.client.set(key, "replacement", px=1000)

        assert await peer.client.get(key) == "replacement"
        await peer.client.delete(key)
        async with peer.lease("shared-job", 0.06) as peer_acquired:
            assert peer_acquired
    finally:
        await peer.close()


async def test_settings_snapshot_is_shared_between_clients(redis_backend):
    peer = await _peer(redis_backend)
    values = {"sse_max_connections_per_user": 7, "custom": ["shared"]}
    try:
        await settings_store.publish(values)

        raw = await peer.client.get(peer.key("settings", "snapshot"))
        assert raw is not None
        assert json.loads(raw) == values
        assert await peer.client.get(peer.key("settings", "version")) == "1"

        await settings_store.apply_snapshot({"sse_max_connections_per_user": 1})
        await settings_store.sync_from_redis()
        assert settings_store.get_int("sse_max_connections_per_user") == 7
        assert settings_store.get_list("custom") == ["shared"]
    finally:
        await peer.close()


async def test_sse_limit_and_release_are_shared_between_clients(redis_backend, monkeypatch):
    peer = await _peer(redis_backend)
    try:
        monkeypatch.setattr(sse, "get_redis", lambda: redis_backend)
        first_lease = await sse.acquire("shared-user", limit=1)

        monkeypatch.setattr(sse, "get_redis", lambda: peer)
        with pytest.raises(HTTPException) as exc_info:
            await sse.acquire("shared-user", limit=1)
        assert exc_info.value.status_code == 429

        await sse.release("shared-user", "not-the-owner")
        with pytest.raises(HTTPException):
            await sse.acquire("shared-user", limit=1)

        monkeypatch.setattr(sse, "get_redis", lambda: redis_backend)
        await sse.release("shared-user", first_lease)
        monkeypatch.setattr(sse, "get_redis", lambda: peer)
        second_lease = await sse.acquire("shared-user", limit=1)
        await sse.release("shared-user", second_lease)
    finally:
        await peer.close()


async def test_sse_slot_renews_until_owner_releases(redis_backend, monkeypatch):
    peer = await _peer(redis_backend)
    try:
        monkeypatch.setattr(sse, "_LEASE_SECONDS", 0.06)
        monkeypatch.setattr(sse, "get_redis", lambda: redis_backend)
        lease_id = await sse.acquire("long-stream", limit=1)
        await asyncio.sleep(0.14)

        monkeypatch.setattr(sse, "get_redis", lambda: peer)
        with pytest.raises(HTTPException):
            await sse.acquire("long-stream", limit=1)

        monkeypatch.setattr(sse, "get_redis", lambda: redis_backend)
        await sse.release("long-stream", lease_id)
        monkeypatch.setattr(sse, "get_redis", lambda: peer)
        next_lease = await sse.acquire("long-stream", limit=1)
        await sse.release("long-stream", next_lease)
    finally:
        await peer.close()


async def test_task_tick_executes_once_across_managers(redis_backend, monkeypatch):
    peer = await _peer(redis_backend)
    first_manager = TaskManager()
    second_manager = TaskManager()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    first_task = PeriodicTask("shared", tick, "unused", min_interval=1)
    second_task = PeriodicTask("shared", tick, "unused", min_interval=1)
    try:
        first_run = asyncio.create_task(first_manager._run_tick(first_task))
        await asyncio.wait_for(entered.wait(), timeout=1)

        from voidswitch.tasks import manager as manager_module

        with monkeypatch.context() as patch:
            patch.setattr(manager_module, "get_redis", lambda: peer)
            assert await second_manager._run_tick(second_task) is False

        release.set()
        assert await first_run is True
        assert calls == 1
        assert first_task.runs == 1
        assert second_task.runs == 0
    finally:
        release.set()
        await peer.close()
