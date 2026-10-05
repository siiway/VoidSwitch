"""Redis-backed coordination shared by provider OAuth implementations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from voidswitch.core.redis import get_redis


@dataclass(frozen=True, slots=True)
class PendingLogin:
    verifier: str
    provider_id: int
    claim_id: str | None = None


class LoginStateStore:
    def __init__(self, flow: str, ttl_seconds: int) -> None:
        self._flow = flow
        self._ttl_seconds = ttl_seconds

    def _key(self, state: str) -> str:
        return get_redis().key("oauth", "login", self._flow, state)

    async def put(self, state: str, verifier: str, provider_id: int) -> None:
        value = json.dumps({"verifier": verifier, "provider_id": provider_id})
        await get_redis().client.set(self._key(state), value, ex=self._ttl_seconds)

    async def peek(self, state: str) -> PendingLogin | None:
        key = self._key(state)
        value = await get_redis().client.get(key)
        if value is None:
            return None
        try:
            data = json.loads(value)
            return PendingLogin(
                verifier=str(data["verifier"]), provider_id=int(data["provider_id"])
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await get_redis().client.delete(key)
            return None

    @asynccontextmanager
    async def claim(self, state: str) -> AsyncIterator[PendingLogin | None]:
        claim_id = uuid4().hex
        async with get_redis().lease(
            f"oauth-login:{self._flow}:{state}", ttl_seconds=60
        ) as acquired:
            if not acquired:
                yield None
                return
            pending = await self.peek(state)
            yield (
                PendingLogin(pending.verifier, pending.provider_id, claim_id)
                if pending is not None
                else None
            )

    async def discard(self, state: str) -> None:
        await get_redis().client.delete(self._key(state))


@asynccontextmanager
async def refresh_lease(flow: str, key_id: int) -> AsyncIterator[None]:
    """Wait for an ownership-safe lease covering one credential rotation."""
    redis = get_redis()
    while True:
        async with redis.lease(f"oauth-refresh:{flow}:{key_id}", ttl_seconds=60) as acquired:
            if acquired:
                yield
                return
        await asyncio.sleep(0.05)
