from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from url_shortener.models.base import Base


class RedirectEvent(Base):
    __tablename__ = "redirect_events"
    __table_args__ = (
        Index(
            "ix_redirect_events_short_code_occurred_at",
            "short_code",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    short_code: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("urls.short_code", ondelete="RESTRICT"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
