from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from url_shortener.core.database import get_session
from url_shortener.core.security import create_access_token
from url_shortener.main import create_app
from url_shortener.models.base import Base
from url_shortener.models.user import User
from url_shortener.models.url import Url
from url_shortener.services import urls as url_service


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


def test_register_user_success(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "securepassword123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert "id" in data
    assert "password" not in data
    assert "hashed_password" not in data

    with session_factory() as session:
        user = session.scalars(select(User).where(User.email == "alice@example.com")).one()
        assert user.is_active is True
        assert user.hashed_password != "securepassword123"


def test_register_duplicate_email_fails(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "password123"},
    )
    duplicate_res = client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "differentpassword"},
    )
    assert duplicate_res.status_code == 400
    assert "already exists" in duplicate_res.json()["detail"]


def test_register_short_password_fails(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_login_success(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "carolpassword"},
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "carolpassword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_password_fails(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "correctpassword"},
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password."


def test_login_unknown_user_fails(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "password123"},
    )
    assert response.status_code == 401


def test_get_current_user_profile(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "eve@example.com", "password": "evepassword"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "eve@example.com", "password": "evepassword"},
    )
    token = login_res.json()["access_token"]

    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "eve@example.com"


def test_get_profile_without_token_fails(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_get_profile_with_expired_token_fails(client: TestClient) -> None:
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-10))
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_authenticated_url_creation_and_ownership(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "ownerpassword"},
    )
    user_id = reg.json()["id"]
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "ownerpassword"},
    ).json()["access_token"]

    # Create URL with Bearer token
    create_res = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/owned-url"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code == 201

    with session_factory() as session:
        url = session.scalars(select(Url)).one()
        assert url.user_id == user_id

    # Retrieve my URLs
    my_urls_res = client.get(
        "/api/v1/urls/my",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert my_urls_res.status_code == 200
    urls_list = my_urls_res.json()
    assert len(urls_list) == 1
    assert urls_list[0]["original_url"] == "https://example.com/owned-url"


def test_anonymous_url_creation_remains_allowed(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    # URL creation without token produces unassociated URL (user_id = None)
    response = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/anon-url"},
    )
    assert response.status_code == 201
    with session_factory() as session:
        url = session.scalars(select(Url)).one()
        assert url.user_id is None
