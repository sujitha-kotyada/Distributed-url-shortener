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
