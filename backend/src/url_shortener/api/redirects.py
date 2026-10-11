from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from url_shortener.core.database import get_session
from url_shortener.services.urls import UrlLookupError, get_url_by_short_code


router = APIRouter(tags=["redirects"])


@router.get(
    "/{short_code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
def redirect_short_url(
    short_code: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    try:
        url = get_url_by_short_code(session=session, short_code=short_code)
    except UrlLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not look up URL.",
        ) from exc

    if url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short URL not found.",
        )

    return RedirectResponse(
        url=url.original_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
