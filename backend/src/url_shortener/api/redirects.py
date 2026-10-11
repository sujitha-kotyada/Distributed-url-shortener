import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from url_shortener.core.database import get_session
from url_shortener.services.analytics import (
    AnalyticsRecordingError,
    RedirectAnalytics,
)
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

    analytics: RedirectAnalytics = request.app.state.redirect_analytics
    try:
        analytics.record_redirect(session=session, short_code=short_code)
    except AnalyticsRecordingError:
        logger.warning("Redirect analytics recording failed.")

    return RedirectResponse(
        url=original_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
