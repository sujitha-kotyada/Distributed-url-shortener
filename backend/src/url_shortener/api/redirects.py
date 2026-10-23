import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from url_shortener.api.deps import get_client_ip
from url_shortener.core.config import get_settings
from url_shortener.core.database import get_session
from url_shortener.core.metrics import PrometheusMetricsCollector
from url_shortener.services.analytics import RedirectEventMessage
from url_shortener.services.streams import AnalyticsPublishError
from url_shortener.services.urls import UrlLookupError, resolve_redirect_target


router = APIRouter(tags=["redirects"])
logger = logging.getLogger(__name__)


@router.get(
    "/{short_code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
def redirect_short_url(
    request: Request,
    short_code: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        client_ip = get_client_ip(request)
        settings = get_settings()
        limit_res = limiter.check(
            action="redirect",
            identifier=client_ip,
            limit=settings.rate_limit_redirect_per_minute,
            window_seconds=60,
        )
        if not limit_res.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded for short link redirects. Please try again later.",
                headers={
                    "Retry-After": str(limit_res.reset_seconds),
                    "X-RateLimit-Limit": str(limit_res.limit),
                    "X-RateLimit-Remaining": str(limit_res.remaining),
                },
            )
    try:
        original_url = resolve_redirect_target(
            session=session,
            short_code=short_code,
            cache=getattr(request.app.state, "redirect_cache", None),
        )
    except UrlLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not look up URL.",
        ) from exc

    if original_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short URL not found.",
        )

    event = RedirectEventMessage(
        event_id=uuid4(),
        short_code=short_code,
        occurred_at=datetime.now(UTC),
    )
    publisher = getattr(request.app.state, "analytics_publisher", None)
    if publisher is None:
        logger.warning("Redirect analytics event was not published.")
    else:
        try:
            publisher.publish(event)
        except AnalyticsPublishError:
            logger.warning("Redirect analytics event was not published.")

    PrometheusMetricsCollector.get_instance().increment_redirect()

    return RedirectResponse(
        url=original_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
