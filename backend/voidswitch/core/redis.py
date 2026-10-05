"""Process-wide Redis client and namespaced coordination primitives."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RedisConfig:
    url: str
    key_prefix: str = "voidswitch"
    max_connections: int = 50
    connect_timeout: float = 2.0
    socket_timeout: float = 2.0


class RedisService:
    def __init__(self, config: RedisConfig) -> None:
        self.prefix = config.key_prefix.strip(":")
        self.client = Redis.from_url(
            config.url,
            decode_responses=True,
            max_connections=config.max_connections,
            socket_connect_timeout=config.connect_timeout,
            socket_timeout=config.socket_timeout,
            health_check_interval=30,
        )

    def key(self, *parts: object) -> str:
        return ":".join((self.prefix, *(str(part) for part in parts)))

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        await self.client.aclose()

    @asynccontextmanager
    async def lease(self, name: str, ttl_seconds: float) -> AsyncIterator[bool]:
        key = self.key("lease", name)
        owner = uuid4().hex
        ttl_ms = max(1, int(ttl_seconds * 1000))
        acquired = bool(await self.client.set(key, owner, nx=True, px=ttl_ms))
        renewal: asyncio.Task[None] | None = None
        if acquired:
            renewal = asyncio.create_task(
                self._renew_lease(key, owner, ttl_ms), name=f"redis:lease:{name}"
            )
        try:
            yield acquired
        finally:
            if acquired:
                assert renewal is not None
                renewal.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await renewal
                await self.client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    key,
                    owner,
                )

    async def _renew_lease(self, key: str, owner: str, ttl_ms: int) -> None:
        interval = max(0.01, ttl_ms / 3000)
        while True:
            await asyncio.sleep(interval)
            renewed = await self.client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end",
                1,
                key,
                owner,
                ttl_ms,
            )
            if not renewed:
                return


_service: RedisService | None = None


async def init_redis(config: RedisConfig) -> RedisService:
    global _service
    service = RedisService(config)
    await service.ping()
    _service = service
    return service


def get_redis() -> RedisService:
    if _service is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _service


async def close_redis() -> None:
    global _service
    if _service is not None:
        await _service.close()
        _service = None
