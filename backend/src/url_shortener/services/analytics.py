from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from url_shortener.models.redirect_event import RedirectEvent


class AnalyticsRecordingError(RuntimeError):
    """Raised when an analytics event cannot be persisted."""


class RedirectEventMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    short_code: str
    occurred_at: datetime

    @field_validator("short_code")
    @classmethod
    def validate_short_code(cls, value: str) -> str:
        if value == "" or len(value) > 32:
            raise ValueError("short_code must contain 1 to 32 characters.")
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include timezone information.")
        return value.astimezone(UTC)


class RedirectEventPublisher(Protocol):
    def publish(self, event: RedirectEventMessage) -> None: ...


class PostgresRedirectAnalytics:
    """Persist stream events with at-least-once, idempotent processing."""

    def record_event(
        self,
        *,
        session: Session,
        event: RedirectEventMessage,
    ) -> None:
        try:
            session.add(
                RedirectEvent(
                    event_id=str(event.event_id),
                    short_code=event.short_code,
                    occurred_at=event.occurred_at,
                )
            )
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            try:
                existing_event = session.scalar(
                    select(RedirectEvent).where(
                        RedirectEvent.event_id == str(event.event_id)
                    )
                )
            except SQLAlchemyError as lookup_exc:
                session.rollback()
                raise AnalyticsRecordingError(
                    "Database error while checking analytics event id."
                ) from lookup_exc
            if existing_event is not None:
                return
            raise AnalyticsRecordingError(
                "Analytics event violates a database constraint."
            ) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise AnalyticsRecordingError(
                "Database error while recording analytics event."
            ) from exc

    def record_redirect(self, *, session: Session, short_code: str) -> None:
        self.record_event(
            session=session,
            event=RedirectEventMessage(
                event_id=uuid4(),
                short_code=short_code,
                occurred_at=datetime.now(UTC),
            ),
        )
