from collections.abc import Generator
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from url_shortener.core.database import get_session
from url_shortener.main import create_app
from url_shortener.models.base import Base
from url_shortener.models.redirect_event import RedirectEvent
from url_shortener.models.url import Url
from url_shortener.services.analytics import (
    AnalyticsRecordingError,
    PostgresRedirectAnalytics,
)
from url_shortener.services import urls as url_service
from url_shortener.services.urls import UrlLookupError


class FakeRedirectCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, short_code: str) -> str | None:
        return self.values.get(short_code)

    def set(self, short_code: str, original_url: str) -> None:
        self.values[short_code] = original_url


class FailingAnalytics:
    def record_redirect(self, *, session: Session, short_code: str) -> None:
        raise AnalyticsRecordingError("analytics unavailable")


class RecordingAnalytics:
    def __init__(self) -> None:
        self.short_codes: list[str] = []

    def record_redirect(self, *, session: Session, short_code: str) -> None:
        self.short_codes.append(short_code)


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
def client(
    session_factory: sessionmaker[Session],
) -> Generator[tuple[TestClient, FakeRedirectCache], None, None]:
    app = create_app()
    cache = FakeRedirectCache()

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        app.state.redirect_cache = cache
        yield test_client, cache

    app.dependency_overrides.clear()


def add_url(session_factory: sessionmaker[Session], short_code: str) -> None:
    with session_factory() as session:
        session.add(
            Url(
                id=1,
                short_code=short_code,
                original_url="https://example.com/analytics-target",
            )
        )
        session.commit()


def get_events(session_factory: sessionmaker[Session]) -> list[RedirectEvent]:
    with session_factory() as session:
        return list(session.scalars(select(RedirectEvent)).all())


def test_redirect_persists_one_event_on_cache_miss(
    client: tuple[TestClient, FakeRedirectCache],
    session_factory: sessionmaker[Session],
) -> None:
    test_client, cache = client
    add_url(session_factory, "miss")

    response = test_client.get("/miss", follow_redirects=False)

    assert response.status_code == 307
    assert cache.values["miss"] == "https://example.com/analytics-target"
    events = get_events(session_factory)
    assert len(events) == 1
    assert events[0].short_code == "miss"


def test_redirect_persists_one_event_on_cache_hit(
    client: tuple[TestClient, FakeRedirectCache],
    session_factory: sessionmaker[Session],
) -> None:
    test_client, cache = client
    add_url(session_factory, "hit")
    cache.values["hit"] = "https://example.com/analytics-target"

    response = test_client.get("/hit", follow_redirects=False)

    assert response.status_code == 307
    events = get_events(session_factory)
    assert len(events) == 1
    assert events[0].short_code == "hit"


def test_unknown_short_code_does_not_persist_event(
    client: tuple[TestClient, FakeRedirectCache],
    session_factory: sessionmaker[Session],
) -> None:
    response = client[0].get("/missing", follow_redirects=False)

    assert response.status_code == 404
    assert get_events(session_factory) == []


def test_redirect_succeeds_when_analytics_persistence_fails(
    client: tuple[TestClient, FakeRedirectCache],
    session_factory: sessionmaker[Session],
) -> None:
    test_client, _ = client
    add_url(session_factory, "analytics-failure")
    test_client.app.state.redirect_analytics = FailingAnalytics()

    response = test_client.get("/analytics-failure", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://example.com/analytics-target"
    assert get_events(session_factory) == []


def test_redirect_lookup_failure_is_not_treated_as_analytics_failure(
    client: tuple[TestClient, FakeRedirectCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _ = client
    analytics = RecordingAnalytics()
    test_client.app.state.redirect_analytics = analytics

    def fail_lookup(*, session: Session, short_code: str) -> Url | None:
        raise UrlLookupError("lookup failed")

    monkeypatch.setattr(url_service, "get_url_by_short_code", fail_lookup)

    response = test_client.get("/lookup-failure", follow_redirects=False)

    assert response.status_code == 500
    assert response.json() == {"detail": "Could not look up URL."}
    assert analytics.short_codes == []


def test_postgres_analytics_rolls_back_failed_write() -> None:
    session = Mock()
    session.commit.side_effect = SQLAlchemyError("write failed")

    with pytest.raises(AnalyticsRecordingError):
        PostgresRedirectAnalytics().record_redirect(
            session=session,
            short_code="abc",
        )

    session.rollback.assert_called_once()
