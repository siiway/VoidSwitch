"""Redis-backed cross-worker sliding-window rate limiting."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from voidswitch.core.redis import RedisService, get_redis

_ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local cutoff = now_ms - tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]) + 1000)
return 1
"""

_RESERVE_ANY_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local best = 0
local best_remaining = 0
for i = 1, #KEYS do
  local window = tonumber(ARGV[(i - 1) * 2 + 1])
  local maximum = tonumber(ARGV[(i - 1) * 2 + 2])
  if maximum <= 0 or window <= 0 then return 1 end
  redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now_ms - window)
  local remaining = maximum - redis.call('ZCARD', KEYS[i])
  if remaining > best_remaining then best = i; best_remaining = remaining end
end
if best == 0 then return 0 end
local window = tonumber(ARGV[(best - 1) * 2 + 1])
redis.call('ZADD', KEYS[best], now_ms, ARGV[#ARGV])
redis.call('PEXPIRE', KEYS[best], window + 1000)
return 1
"""


@dataclass(frozen=True, slots=True)
class LimitCandidate:
    key: str
    window_seconds: float
    max_requests: int


class RedisRateLimiter:
    def __init__(self, redis: RedisService | None = None, namespace: str = "rate") -> None:
        self._redis = redis
        self._namespace = namespace

    @property
    def redis(self) -> RedisService:
        return self._redis or get_redis()

    async def acquire(self, key: str, *, window_seconds: float, max_requests: int) -> bool:
        if max_requests <= 0 or window_seconds <= 0:
            return True
        result = await self.redis.client.eval(
            _ACQUIRE_SCRIPT,
            1,
            self.redis.key(self._namespace, key),
            max(1, int(window_seconds * 1000)),
            max_requests,
            uuid4().hex,
        )
        return bool(result)

    async def reserve_any(self, candidates: list[LimitCandidate]) -> bool:
        if not candidates:
            return True
        keys = [self.redis.key(self._namespace, candidate.key) for candidate in candidates]
        args: list[str | int] = []
        for candidate in candidates:
            args.extend((max(1, int(candidate.window_seconds * 1000)), candidate.max_requests))
        args.append(uuid4().hex)
        return bool(await self.redis.client.eval(_RESERVE_ANY_SCRIPT, len(keys), *keys, *args))


operation_limiter = RedisRateLimiter(namespace="rate:operation")
call_limiter = RedisRateLimiter(namespace="rate:call")
gateway_rpm_limiter = RedisRateLimiter(namespace="rate:rpm")
