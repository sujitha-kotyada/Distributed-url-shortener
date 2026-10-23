from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


from url_shortener.core.database import get_session
from url_shortener.core.rate_limit import DistributedRateLimiter, RateLimitResult
from url_shortener.main import create_app
from url_shortener.models.base import Base
from url_shortener.models.url import Url
from url_shortener.services import urls as url_service
from url_shortener.services.urls import resolve_redirect_target


class FakeLimiter:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str, int, int]] = []

    def check(self, *, action: str, identifier: str, limit: int, window_seconds: int = 60) -> RateLimitResult:
        self.calls.append((action, identifier, limit, window_seconds))
        return RateLimitResult(
            allowed=self.allow,
            limit=limit,
            remaining=0 if not self.allow else limit - 1,
            reset_seconds=60,
        )


class FakeCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted: list[str] = []

    def get(self, short_code: str) -> str | None:
        return self.data.get(short_code)

    def set(self, short_code: str, original_url: str) -> None:
        self.data[short_code] = original_url

    def delete(self, short_code: str) -> None:
        self.deleted.append(short_code)
        self.data.pop(short_code, None)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(url_service, "allocate_url_id", lambda s: 1)
    app = create_app()

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_url_creation_rate_limit_exceeded(client: TestClient) -> None:
    client.app.state.rate_limiter = FakeLimiter(allow=False)

    response = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/test"},
    )

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]
    assert response.headers["retry-after"] == "60"
    assert response.headers["x-ratelimit-remaining"] == "0"


def test_redirect_rate_limit_exceeded(client: TestClient) -> None:
    client.app.state.rate_limiter = FakeLimiter(allow=False)

    response = client.get("/abc", follow_redirects=False)

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]


def test_cors_headers_set_on_allowed_origin(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_inactive_url_does_not_redirect_and_clears_cache(session_factory: sessionmaker[Session]) -> None:
    cache = FakeCache()
    cache.set("inactive", "https://example.com/inactive")

    with session_factory() as session:
        session.add(
            Url(
                id=1,
                short_code="inactive",
                original_url="https://example.com/inactive",
                is_active=True,
            )
        )
        session.commit()

        # Active URL in cache is invalidated upon deactivation
        assert url_service.deactivate_url(session=session, short_code="inactive", cache=cache) is True
        assert "inactive" in cache.deleted
        assert cache.get("inactive") is None

        # Subsequent redirect resolution returns None
        result = resolve_redirect_target(session=session, short_code="inactive", cache=cache)
        assert result is None


def test_expired_url_does_not_redirect_on_cache_miss(session_factory: sessionmaker[Session]) -> None:
    cache = FakeCache()
    past = datetime.now(UTC) - timedelta(hours=1)
    with session_factory() as session:
        session.add(
            Url(
                id=2,
                short_code="expired",
                original_url="https://example.com/expired",
                expires_at=past,
                is_active=True,
            )
        )
        session.commit()

        result = resolve_redirect_target(session=session, short_code="expired", cache=cache)
        assert result is None
        assert cache.get("expired") is None


def test_rate_limiter_lua_execution() -> None:
    client_mock = Mock()
    client_mock.register_script.return_value = Mock(return_value=[1, 19, 60])
    limiter = DistributedRateLimiter(client_mock)

    res = limiter.check(action="create_url", identifier="127.0.0.1", limit=20)
    assert res.allowed is True
    assert res.remaining == 19
    assert res.limit == 20


def test_get_client_ip_direct_without_trusted_proxies() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({
        "type": "http",
        "client": ("198.51.100.25", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 1.1.1.1")],
    })
    # Untrusted proxy / no trusted proxy configured: peer IP is used, spoofed header ignored
    assert get_client_ip(req, trusted_proxies=[]) == "198.51.100.25"


def test_get_client_ip_direct_with_trusted_proxies_ignores_spoof() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({
        "type": "http",
        "client": ("198.51.100.25", 54321),
        "headers": [(b"x-forwarded-for", b"10.0.0.1")],
    })
    # Connecting peer is not in trusted CIDR 10.0.0.0/8: header ignored
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8"]) == "198.51.100.25"


def test_get_client_ip_from_trusted_proxy() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({
        "type": "http",
        "client": ("10.0.1.5", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.88")],
    })
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8"]) == "203.0.113.88"


def test_get_client_ip_from_trusted_proxy_spoofed_chain_picks_real_client() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    # Malicious client spoofed "1.1.1.1", trusted Nginx appended the real client "203.0.113.88"
    req = Request({
        "type": "http",
        "client": ("10.0.1.5", 54321),
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 203.0.113.88")],
    })
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8"]) == "203.0.113.88"


def test_get_client_ip_multiple_trusted_proxies() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    # Client -> Cloudflare (198.41.128.5) -> Nginx (10.0.1.5) -> Backend
    req = Request({
        "type": "http",
        "client": ("10.0.1.5", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.99, 198.41.128.5")],
    })
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8", "198.41.128.0/17"]) == "203.0.113.99"


def test_get_client_ip_malformed_forwarded_ip_handled_safely() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({
        "type": "http",
        "client": ("10.0.1.5", 54321),
        "headers": [(b"x-forwarded-for", b"not-a-valid-ip")],
    })
    # Malformed IP does not crash and is returned as the untrusted candidate string
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8"]) == "not-a-valid-ip"


def test_get_client_ip_fallback_to_x_real_ip_from_trusted_proxy() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({
        "type": "http",
        "client": ("10.0.1.5", 54321),
        "headers": [(b"x-real-ip", b"203.0.113.77")],
    })
    assert get_client_ip(req, trusted_proxies=["10.0.0.0/8"]) == "203.0.113.77"


def test_get_client_ip_missing_client_host() -> None:
    from fastapi import Request
    from url_shortener.api.deps import get_client_ip

    req = Request({"type": "http", "client": None, "headers": []})
    assert get_client_ip(req, trusted_proxies=[]) == "127.0.0.1"
