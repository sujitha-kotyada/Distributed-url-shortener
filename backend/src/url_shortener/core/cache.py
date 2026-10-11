from typing import Protocol

import redis

from url_shortener.core.config import Settings


REDIRECT_CACHE_PREFIX = "url_shortener:redirect:"


class RedisCacheError(RuntimeError):
    """Raised when Redis cannot serve a cache operation."""


class RedirectCache(Protocol):
    def get(self, short_code: str) -> str | None: ...

    def set(self, short_code: str, original_url: str) -> None: ...


class RedisRedirectCache:
    def __init__(self, client: redis.Redis, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def key_for(short_code: str) -> str:
        return f"{REDIRECT_CACHE_PREFIX}{short_code}"

    def get(self, short_code: str) -> str | None:
        try:
            return self._client.get(self.key_for(short_code))
        except redis.RedisError as exc:
            raise RedisCacheError("Redis read failed.") from exc

    def set(self, short_code: str, original_url: str) -> None:
        try:
            self._client.set(
                self.key_for(short_code),
                original_url,
                ex=self._ttl_seconds,
            )
        except redis.RedisError as exc:
            raise RedisCacheError("Redis write failed.") from exc

    def close(self) -> None:
        self._client.close()


def create_redirect_cache(settings: Settings) -> RedisRedirectCache | None:
    if settings.redis_url is None:
        return None

    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
    )
    return RedisRedirectCache(client, settings.redis_cache_ttl_seconds)
