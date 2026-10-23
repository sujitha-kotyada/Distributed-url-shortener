from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from url_shortener.core.database import get_session
from url_shortener.main import create_app
from url_shortener.models.base import Base
from url_shortener.models.redirect_event import RedirectEvent
from url_shortener.models.url import Url
from url_shortener.models.user import User


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
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_query_stats_empty_url(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add(Url(id=1, short_code="empty", original_url="https://example.com/empty"))
        session.commit()

    response = client.get("/api/v1/urls/empty/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["short_code"] == "empty"
    assert data["total_clicks"] == 0
    assert data["clicks_by_period"] == []
    assert data["recent_events"] == []


def test_query_stats_with_aggregated_events(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(Url(id=1, short_code="active", original_url="https://example.com/active"))
        # Add 3 redirect events
        for i in range(3):
            session.add(
                RedirectEvent(
                    id=i + 1,
                    event_id=str(uuid4()),
                    short_code="active",
                    occurred_at=now - timedelta(hours=i),
                )
            )
        session.commit()

    response = client.get("/api/v1/urls/active/stats?days=7&interval=hour")
    assert response.status_code == 200
    data = response.json()
    assert data["total_clicks"] == 3
    assert len(data["recent_events"]) == 3
    assert len(data["clicks_by_period"]) >= 1


def test_query_stats_nonexistent_url_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/urls/missing/stats")
    assert response.status_code == 404
    assert response.json()["detail"] == "Short URL not found."


def test_query_stats_ownership_enforcement(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    # Register two users
    client.post("/api/v1/auth/register", json={"email": "alice@test.com", "password": "password123"})
    client.post("/api/v1/auth/register", json={"email": "bob@test.com", "password": "password123"})

    alice_token = client.post("/api/v1/auth/login", json={"email": "alice@test.com", "password": "password123"}).json()["access_token"]
    bob_token = client.post("/api/v1/auth/login", json={"email": "bob@test.com", "password": "password123"}).json()["access_token"]

    # Alice owns 'alice_url'
    with session_factory() as session:
        alice = session.query(User).filter_by(email="alice@test.com").one()
        session.add(Url(id=10, short_code="alice_url", original_url="https://example.com/alice", user_id=alice.id))
        session.commit()

    # Alice can view stats
    res_alice = client.get(
        "/api/v1/urls/alice_url/stats",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert res_alice.status_code == 200

    # Bob cannot view Alice's URL stats
    res_bob = client.get(
        "/api/v1/urls/alice_url/stats",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert res_bob.status_code == 403
    assert "permission" in res_bob.json()["detail"]

    # Anonymous user cannot view Alice's private URL stats
    res_anon = client.get("/api/v1/urls/alice_url/stats")
    assert res_anon.status_code == 403
