from fastapi.testclient import TestClient

from url_shortener.main import create_app


def test_health_returns_application_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Distributed URL Shortener",
        "environment": "development",
    }

