import logging
import time
from dataclasses import dataclass

import redis

logger = logging.getLogger(__name__)

SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
local current_requests = redis.call('ZCARD', key)
if current_requests < limit then
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, window)
    return {1, limit - current_requests - 1, window}
else
    return {0, 0, window}
end
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class DistributedRateLimiter:
    """Atomic Redis sliding-window distributed rate limiter."""

    def __init__(self, client: redis.Redis | None) -> None:
        self._client = client
        self._script = None
        if self._client is not None:
            try:
                self._script = self._client.register_script(SLIDING_WINDOW_LUA)
            except Exception as exc:
                logger.warning("Could not register rate-limiting Lua script: %s", exc)

    def check(
        self,
        *,
        action: str,
        identifier: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitResult:
        if self._client is None:
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=window_seconds,
            )

        key = f"url_shortener:rate_limit:{action}:{identifier}"
        now = int(time.time())
        try:
            if self._script is not None:
                res = self._script(keys=[key], args=[now, window_seconds, limit])
            else:
                res = self._client.eval(SLIDING_WINDOW_LUA, 1, key, now, window_seconds, limit)
            allowed = bool(res[0])
            remaining = int(res[1])
            reset = int(res[2])
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=remaining,
                reset_seconds=reset,
            )
        except redis.RedisError as exc:
            logger.warning("Redis error during rate limiting check for %s: %s", identifier, exc)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=window_seconds,
            )


def create_rate_limiter(redis_url: str | None) -> DistributedRateLimiter:
    if redis_url is None:
        return DistributedRateLimiter(None)
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
        return DistributedRateLimiter(client)
    except Exception as exc:
        logger.warning("Could not initialize rate limiter Redis client: %s", exc)
        return DistributedRateLimiter(None)
