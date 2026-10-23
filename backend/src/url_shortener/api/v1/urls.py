from datetime import UTC
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from url_shortener.api.deps import (
    get_client_ip,
    get_current_user,
    get_optional_current_user,
)
from url_shortener.core.config import get_settings
from url_shortener.core.database import get_session
from url_shortener.models.user import User
from url_shortener.schemas.analytics import UrlStatsResponse
from url_shortener.schemas.url import UrlCreateRequest, UrlCreateResponse
from url_shortener.services.urls import (
    UrlCreationError,
    create_short_url,
    get_user_urls,
)


router = APIRouter(tags=["urls"])


@router.post(
    "/urls",
    response_model=UrlCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_url(
    http_request: Request,
    request: UrlCreateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_current_user),
) -> UrlCreateResponse:
    settings = get_settings()
    limiter = getattr(http_request.app.state, "rate_limiter", None)
    if limiter is not None:
        client_ip = get_client_ip(http_request)
        limit_res = limiter.check(
            action="create_url",
            identifier=client_ip,
            limit=settings.rate_limit_url_creation_per_minute,
            window_seconds=60,
        )
        if not limit_res.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded for URL creation. Please try again later.",
                headers={
                    "Retry-After": str(limit_res.reset_seconds),
                    "X-RateLimit-Limit": str(limit_res.limit),
                    "X-RateLimit-Remaining": str(limit_res.remaining),
                },
            )

    user_id = current_user.id if current_user is not None else None
    try:
        url = create_short_url(
            session=session,
            original_url=str(request.url),
            user_id=user_id,
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


@router.get(
    "/urls/my",
    response_model=list[UrlCreateResponse],
    status_code=status.HTTP_200_OK,
)
def get_my_urls(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[UrlCreateResponse]:
    settings = get_settings()
    urls = get_user_urls(
        session=session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return [
        UrlCreateResponse(
            short_code=u.short_code,
            short_url=f"{settings.base_url.rstrip('/')}/{u.short_code}",
            original_url=u.original_url,
            created_at=u.created_at.astimezone(UTC),
        )
        for u in urls
    ]


@router.get(
    "/urls/{short_code}/stats",
    response_model=UrlStatsResponse,
    status_code=status.HTTP_200_OK,
)
def get_url_stats_endpoint(
    short_code: str,
    days: int = Query(default=7, ge=1, le=90),
    interval: Literal["hour", "day"] = Query(default="day"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_current_user),
) -> UrlStatsResponse:
    from url_shortener.services.analytics_query import (
        AnalyticsPermissionError,
        UrlNotFoundError,
        query_url_stats,
    )

    requesting_user_id = current_user.id if current_user is not None else None
    try:
        return query_url_stats(
            session=session,
            short_code=short_code,
            requesting_user_id=requesting_user_id,
            days=days,
            interval=interval,
            limit=limit,
        )
    except UrlNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short URL not found.",
        ) from exc
    except AnalyticsPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view analytics for this URL.",
        ) from exc
