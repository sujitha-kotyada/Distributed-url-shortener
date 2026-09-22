from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from url_shortener.core.config import get_settings
from url_shortener.core.database import (
    DatabaseUnavailableError,
    check_database_health,
)


router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return basic application health information."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/health/db", response_model=DatabaseHealthResponse)
def database_health() -> DatabaseHealthResponse:
    """Return database connectivity health without exposing sensitive details."""
    try:
        check_database_health()
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc

    return DatabaseHealthResponse(status="ok", database="ok")
