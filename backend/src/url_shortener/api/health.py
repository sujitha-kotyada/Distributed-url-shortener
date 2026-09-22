from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from url_shortener.core.config import get_settings


router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return basic application health information."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )

