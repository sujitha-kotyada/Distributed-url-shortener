from __future__ import annotations

from fastapi.testclient import TestClient

from url_shortener.main import create_app


def test_metrics_endpoint_returns_prometheus_format():
    app = create_app()
    client = TestClient(app)

    # Trigger an endpoint first to record a metric
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    # Query /metrics
    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    assert "text/plain" in metrics_resp.headers["content-type"]

    content = metrics_resp.text
    assert "url_shortener_http_requests_total" in content
    assert 'path="/health"' in content
    assert 'status="200"' in content
    assert "url_shortener_url_creations_total" in content
    assert "url_shortener_redirects_total" in content
    assert "url_shortener_cache_hits_total" in content
    assert "url_shortener_cache_misses_total" in content


def test_redirect_increments_redirects_total_on_success() -> None:
    from unittest.mock import Mock
    from url_shortener.core.database import get_session
    from url_shortener.core.metrics import PrometheusMetricsCollector
    from url_shortener.models.url import Url

    app = create_app()
    collector = PrometheusMetricsCollector.get_instance()
    initial_redirects = collector.redirects_total

    session = Mock()
    session.scalar.return_value = Url(id=1, short_code="success", original_url="https://example.com/target")
    app.dependency_overrides[get_session] = lambda: session

    client = TestClient(app)
    response = client.get("/success", follow_redirects=False)

    assert response.status_code == 307
    assert collector.redirects_total == initial_redirects + 1


def test_redirect_does_not_increment_redirects_total_on_404() -> None:
    from unittest.mock import Mock
    from url_shortener.core.database import get_session
    from url_shortener.core.metrics import PrometheusMetricsCollector

    app = create_app()
    collector = PrometheusMetricsCollector.get_instance()
    initial_redirects = collector.redirects_total

    session = Mock()
    session.scalar.return_value = None
    app.dependency_overrides[get_session] = lambda: session

    client = TestClient(app)
    response = client.get("/not-found-code", follow_redirects=False)

    assert response.status_code == 404
    assert collector.redirects_total == initial_redirects
