from fastapi import FastAPI

from url_shortener.api.health import router as health_router
from url_shortener.core.config import get_settings
from url_shortener.core.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    return app


app = create_app()

