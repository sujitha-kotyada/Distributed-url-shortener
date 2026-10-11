from contextlib import asynccontextmanager

from fastapi import FastAPI

from url_shortener.api.health import router as health_router
from url_shortener.api.redirects import router as redirects_router
from url_shortener.api.v1.urls import router as urls_router
from url_shortener.core.cache import create_redirect_cache
from url_shortener.core.config import get_settings
from url_shortener.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = create_redirect_cache(get_settings())
    app.state.redirect_cache = cache
    try:
        yield
    finally:
        if cache is not None:
            cache.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(urls_router, prefix="/api/v1")
    app.include_router(redirects_router)
    return app


app = create_app()
