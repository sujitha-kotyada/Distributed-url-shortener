from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from url_shortener.api.health import router as health_router
from url_shortener.api.redirects import router as redirects_router
from url_shortener.api.v1.auth import router as auth_router
from url_shortener.api.v1.urls import router as urls_router
from url_shortener.core.cache import create_redirect_cache
from url_shortener.core.config import get_settings
from url_shortener.core.logging import configure_logging
from url_shortener.core.metrics import PrometheusMiddleware, PrometheusMetricsCollector
from url_shortener.core.rate_limit import create_rate_limiter
from url_shortener.services.streams import create_event_publisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    cache = create_redirect_cache(settings)
    publisher = create_event_publisher(settings)
    rate_limiter = create_rate_limiter(settings.redis_url)

    app.state.redirect_cache = cache
    app.state.analytics_publisher = publisher
    app.state.rate_limiter = rate_limiter
    try:
        yield
    finally:
        if cache is not None:
            cache.close()
        if publisher is not None:
            publisher.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Attach Prometheus request monitoring middleware
    app.add_middleware(PrometheusMiddleware)

    # Configure CORS with explicit allowed origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        from fastapi.responses import PlainTextResponse

        content = PrometheusMetricsCollector.get_instance().generate_prometheus_text()
        return PlainTextResponse(content, media_type="text/plain; version=0.0.4; charset=utf-8")

    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(urls_router, prefix="/api/v1")
    app.include_router(redirects_router)
    return app


app = create_app()
