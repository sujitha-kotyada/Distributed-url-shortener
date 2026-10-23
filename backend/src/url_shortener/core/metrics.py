from collections import defaultdict
from threading import Lock
from time import time
from typing import ClassVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class PrometheusMetricsCollector:
    """Thread-safe in-memory Prometheus metric collector with zero external dependencies."""

    _instance: ClassVar["PrometheusMetricsCollector | None"] = None
    _lock: ClassVar[Lock] = Lock()

    def __init__(self) -> None:
        self.http_requests_total: dict[tuple[str, str, int], int] = defaultdict(int)
        self.url_creations_total: int = 0
        self.redirects_total: int = 0
        self.cache_hits_total: int = 0
        self.cache_misses_total: int = 0
        self.analytics_published_total: int = 0
        self.worker_processed_total: int = 0
        self.worker_failed_total: int = 0
        self.worker_dead_lettered_total: int = 0
        self.lock = Lock()

    @classmethod
    def get_instance(cls) -> "PrometheusMetricsCollector":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def record_request(self, method: str, endpoint: str, status_code: int) -> None:
        with self.lock:
            self.http_requests_total[(method, endpoint, status_code)] += 1

    def increment_url_creation(self) -> None:
        with self.lock:
            self.url_creations_total += 1

    def increment_redirect(self) -> None:
        with self.lock:
            self.redirects_total += 1

    def increment_cache_hit(self) -> None:
        with self.lock:
            self.cache_hits_total += 1

    def increment_cache_miss(self) -> None:
        with self.lock:
            self.cache_misses_total += 1

    def increment_analytics_published(self) -> None:
        with self.lock:
            self.analytics_published_total += 1

    def increment_worker_processed(self) -> None:
        with self.lock:
            self.worker_processed_total += 1

    def increment_worker_failed(self) -> None:
        with self.lock:
            self.worker_failed_total += 1

    def increment_worker_dlq(self) -> None:
        with self.lock:
            self.worker_dead_lettered_total += 1

    def generate_prometheus_text(self) -> str:
        lines: list[str] = [
            "# HELP url_shortener_http_requests_total Total number of HTTP requests processed.",
            "# TYPE url_shortener_http_requests_total counter",
        ]
        with self.lock:
            for (method, endpoint, status_code), count in self.http_requests_total.items():
                lines.append(
                    f'url_shortener_http_requests_total{{method="{method}",path="{endpoint}",status="{status_code}"}} {count}'
                )

            lines.extend([
                "# HELP url_shortener_url_creations_total Total URLs successfully shortened.",
                "# TYPE url_shortener_url_creations_total counter",
                f"url_shortener_url_creations_total {self.url_creations_total}",
                "# HELP url_shortener_redirects_total Total short link redirects performed.",
                "# TYPE url_shortener_redirects_total counter",
                f"url_shortener_redirects_total {self.redirects_total}",
                "# HELP url_shortener_cache_hits_total Total Redis cache hits.",
                "# TYPE url_shortener_cache_hits_total counter",
                f"url_shortener_cache_hits_total {self.cache_hits_total}",
                "# HELP url_shortener_cache_misses_total Total Redis cache misses.",
                "# TYPE url_shortener_cache_misses_total counter",
                f"url_shortener_cache_misses_total {self.cache_misses_total}",
                "# HELP url_shortener_analytics_published_total Total redirect events published to Redis Streams.",
                "# TYPE url_shortener_analytics_published_total counter",
                f"url_shortener_analytics_published_total {self.analytics_published_total}",
                "# HELP url_shortener_worker_processed_total Total analytics events persisted by worker.",
                "# TYPE url_shortener_worker_processed_total counter",
                f"url_shortener_worker_processed_total {self.worker_processed_total}",
                "# HELP url_shortener_worker_failed_total Total analytics events that failed during worker processing.",
                "# TYPE url_shortener_worker_failed_total counter",
                f"url_shortener_worker_failed_total {self.worker_failed_total}",
                "# HELP url_shortener_worker_dead_lettered_total Total analytics events moved to DLQ.",
                "# TYPE url_shortener_worker_dead_lettered_total counter",
                f"url_shortener_worker_dead_lettered_total {self.worker_dead_lettered_total}",
            ])
        lines.append("")
        return "\n".join(lines)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time()
        response = await call_next(request)
        path = request.url.path
        # Sanitize dynamic path to avoid metric cardinality explosion
        if path.startswith("/api/v1/urls/") and path.endswith("/stats"):
            normalized_path = "/api/v1/urls/{code}/stats"
        elif path not in {"/health", "/health/db", "/metrics", "/api/v1/urls", "/api/v1/urls/my", "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/me"}:
            normalized_path = "/{short_code}"
        else:
            normalized_path = path

        PrometheusMetricsCollector.get_instance().record_request(
            method=request.method,
            endpoint=normalized_path,
            status_code=response.status_code,
        )
        return response
