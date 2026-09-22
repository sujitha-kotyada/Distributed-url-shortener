from fastapi.testclient import TestClient

from url_shortener.core.database import DatabaseUnavailableError
from url_shortener.main import create_app


def test_database_health_returns_ok_when_database_is_available(monkeypatch) -> None:
    def healthy_database() -> None:
        return None

    monkeypatch.setattr(
        "url_shortener.api.health.check_database_health",
        healthy_database,
    )
    client = TestClient(create_app())

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_database_health_returns_safe_error_when_database_is_unavailable(
    monkeypatch,
) -> None:
    def unavailable_database() -> None:
        raise DatabaseUnavailableError(
            "could not connect to postgresql://user:password@localhost/db",
        )

    monkeypatch.setattr(
        "url_shortener.api.health.check_database_health",
        unavailable_database,
    )
    client = TestClient(create_app())

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}
