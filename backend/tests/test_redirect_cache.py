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


def test_cache_hit_increments_cache_hits_counter() -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    cache = FakeRedirectCache()
    cache.values["hit-code"] = "https://example.com/hit"
    session = Mock()
    collector = PrometheusMetricsCollector()

    result = resolve_redirect_target(
        session=session,
        short_code="hit-code",
        cache=cache,
        metrics=collector,
    )

    assert result == "https://example.com/hit"
    assert collector.cache_hits_total == 1
    assert collector.cache_misses_total == 0


def test_cache_miss_increments_cache_misses_counter() -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    cache = FakeRedirectCache()
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="miss-code",
        original_url="https://example.com/miss",
    )
    collector = PrometheusMetricsCollector()

    result = resolve_redirect_target(
        session=session,
        short_code="miss-code",
        cache=cache,
        metrics=collector,
    )

    assert result == "https://example.com/miss"
    assert collector.cache_hits_total == 0
    assert collector.cache_misses_total == 1


def test_unusable_empty_cache_entry_increments_cache_misses_counter() -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    cache = FakeRedirectCache()
    cache.values["empty-code"] = ""
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="empty-code",
        original_url="https://example.com/fallback",
    )
    collector = PrometheusMetricsCollector()

    result = resolve_redirect_target(
        session=session,
        short_code="empty-code",
        cache=cache,
        metrics=collector,
    )

    assert result == "https://example.com/fallback"
    assert collector.cache_hits_total == 0
    assert collector.cache_misses_total == 1


def test_cache_read_failure_does_not_increment_hit_or_miss() -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    cache = FakeRedirectCache()
    cache.read_error = True
    session = Mock()
    session.scalar.return_value = Url(
        id=1,
        short_code="err-code",
        original_url="https://example.com/err-fallback",
    )
    collector = PrometheusMetricsCollector()

    result = resolve_redirect_target(
        session=session,
        short_code="err-code",
        cache=cache,
        metrics=collector,
    )

    assert result == "https://example.com/err-fallback"
    assert collector.cache_hits_total == 0
    assert collector.cache_misses_total == 0
