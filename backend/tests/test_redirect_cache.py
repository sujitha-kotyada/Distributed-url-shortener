from unittest.mock import Mock

from url_shortener.core.cache import REDIRECT_CACHE_PREFIX, RedisRedirectCache
from url_shortener.models.url import Url
from url_shortener.services.urls import resolve_redirect_target


class FakeRedirectCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str]] = []
        self.read_error = False
        self.write_error = False

    def get(self, short_code: str) -> str | None:
        self.get_calls.append(short_code)
        if self.read_error:
            from url_shortener.core.cache import RedisCacheError

            raise RedisCacheError("read failed")
        return self.values.get(short_code)

    def set(self, short_code: str, original_url: str) -> None:
        self.set_calls.append((short_code, original_url))
        if self.write_error:
            from url_shortener.core.cache import RedisCacheError

            raise RedisCacheError("write failed")
        self.values[short_code] = original_url


def test_cache_hit_returns_destination_without_database_lookup() -> None:
    cache = FakeRedirectCache()
    cache.values["abc"] = "https://example.com/cached"
    session = Mock()

    result = resolve_redirect_target(
        session=session,
        short_code="abc",
        cache=cache,
    )

    assert result == "https://example.com/cached"
    session.scalar.assert_not_called()
    assert cache.get_calls == ["abc"]


def test_cache_miss_queries_database_and_stores_destination() -> None:
    cache = FakeRedirectCache()
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="abc",
        original_url="https://example.com/database",
    )

    result = resolve_redirect_target(
        session=session,
        short_code="abc",
        cache=cache,
    )

    assert result == "https://example.com/database"
    session.scalar.assert_called_once()
    assert cache.set_calls == [("abc", "https://example.com/database")]


def test_unknown_code_returns_none_without_caching() -> None:
    cache = FakeRedirectCache()
    session = Mock()
    session.scalar.return_value = None

    result = resolve_redirect_target(
        session=session,
        short_code="missing",
        cache=cache,
    )

    assert result is None
    assert cache.set_calls == []


def test_cache_read_failure_falls_back_to_database() -> None:
    cache = FakeRedirectCache()
    cache.read_error = True
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="abc",
        original_url="https://example.com/fallback",
    )

    result = resolve_redirect_target(
        session=session,
        short_code="abc",
        cache=cache,
    )

    assert result == "https://example.com/fallback"
    session.scalar.assert_called_once()


def test_cache_write_failure_does_not_block_database_result() -> None:
    cache = FakeRedirectCache()
    cache.write_error = True
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="abc",
        original_url="https://example.com/write-failure",
    )

    result = resolve_redirect_target(
        session=session,
        short_code="abc",
        cache=cache,
    )

    assert result == "https://example.com/write-failure"


def test_redis_cache_uses_namespaced_key_and_ttl() -> None:
    client = Mock()
    cache = RedisRedirectCache(client, ttl_seconds=300)

    cache.set("abc", "https://example.com/ttl")

    client.set.assert_called_once_with(
        f"{REDIRECT_CACHE_PREFIX}abc",
        "https://example.com/ttl",
        ex=300,
    )
