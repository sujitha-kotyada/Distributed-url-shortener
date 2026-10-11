from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from url_shortener.core.config import get_settings
from url_shortener.core.database import get_session
from url_shortener.main import create_app
from url_shortener.models.base import Base
from url_shortener.models.url import Url
from url_shortener.services import urls as url_service
from url_shortener.services.urls import UrlCreationError, create_short_url


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
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    monkeypatch.setenv("BASE_URL", "http://short.test")
    monkeypatch.setattr(url_service, "allocate_url_id", lambda session: 1)
    app = create_app()

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_create_url_returns_shortened_url_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/some/long/url"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["short_code"] == "1"
    assert body["short_url"] == "http://short.test/1"
    assert body["original_url"] == "https://example.com/some/long/url"
    assert body["created_at"].endswith("Z")
    assert "created_at" in body


def test_create_url_persists_url(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/persisted"},
    )

    assert response.status_code == 201
    body = response.json()

    with session_factory() as session:
        persisted = session.scalars(select(Url)).one()

    assert persisted.id == 1
    assert persisted.short_code == body["short_code"]
    assert persisted.original_url == "https://example.com/persisted"
    assert persisted.is_active is True


def test_create_short_url_uses_allocated_id(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_service, "allocate_url_id", lambda session: 62)

    with session_factory() as session:
        created = create_short_url(
            session=session,
            original_url="https://example.com/allocated",
        )

    assert created.id == 62
    assert created.short_code == "10"


def test_sequence_allocator_does_not_fall_back_to_sqlite(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        with pytest.raises(UrlCreationError, match="requires PostgreSQL"):
            url_service.allocate_url_id(session)


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "not-a-url"},
        {"url": "https://"},
    ],
)
def test_create_url_rejects_malformed_url(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    response = client.post("/api/v1/urls", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///tmp/example",
        "javascript:alert(1)",
        "data:text/plain,hello",
    ],
)
def test_create_url_rejects_unsupported_scheme(
    client: TestClient,
    url: str,
) -> None:
    response = client.post("/api/v1/urls", json={"url": url})

    assert response.status_code == 422
