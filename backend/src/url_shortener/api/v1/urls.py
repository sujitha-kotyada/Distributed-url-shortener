from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from url_shortener.core.config import get_settings
from url_shortener.core.database import get_session
from url_shortener.schemas.url import UrlCreateRequest, UrlCreateResponse
from url_shortener.services.urls import UrlCreationError, create_short_url


router = APIRouter(tags=["urls"])


@router.post(
    "/urls",
    response_model=UrlCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_url(
    request: UrlCreateRequest,
    session: Session = Depends(get_session),
) -> UrlCreateResponse:
    settings = get_settings()
    try:
        url = create_short_url(
            session=session,
            original_url=str(request.url),
        )
    except UrlCreationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create URL.",
        ) from exc

    return UrlCreateResponse(
        short_code=url.short_code,
        short_url=f"{settings.base_url.rstrip('/')}/{url.short_code}",
        original_url=url.original_url,
        created_at=url.created_at.astimezone(UTC),
    )
