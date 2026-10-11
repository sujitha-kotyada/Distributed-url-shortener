from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from url_shortener.models.redirect_event import RedirectEvent


class AnalyticsRecordingError(RuntimeError):
    """Raised when a redirect analytics event cannot be persisted."""


class RedirectAnalytics(Protocol):
    def record_redirect(self, *, session: Session, short_code: str) -> None: ...


class PostgresRedirectAnalytics:
    """Persist redirect events synchronously as best effort."""

    def record_redirect(self, *, session: Session, short_code: str) -> None:
        try:
            session.add(RedirectEvent(short_code=short_code))
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise AnalyticsRecordingError(
                "Database error while recording redirect analytics."
            ) from exc
