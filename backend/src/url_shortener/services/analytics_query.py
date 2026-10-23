from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from url_shortener.models.redirect_event import RedirectEvent
from url_shortener.models.url import Url
from url_shortener.schemas.analytics import (
    RecentEventItem,
    TimeSeriesPoint,
    UrlStatsResponse,
)


class UrlNotFoundError(RuntimeError):
    """Raised when short code does not exist."""


class AnalyticsPermissionError(RuntimeError):
    """Raised when a user attempts to access analytics for a URL they do not own."""


def query_url_stats(
    *,
    session: Session,
    short_code: str,
    requesting_user_id: int | None = None,
    days: int = 7,
    interval: Literal["hour", "day"] = "day",
    limit: int = 50,
) -> UrlStatsResponse:
    url = session.scalar(select(Url).where(Url.short_code == short_code))
    if url is None:
        raise UrlNotFoundError(f"Short URL {short_code!r} was not found.")

    # Ownership check: if URL is owned by a user, only that user may view its analytics
    if url.user_id is not None and url.user_id != requesting_user_id:
        raise AnalyticsPermissionError("You do not have permission to view analytics for this URL.")

    # Total clicks count
    total_clicks = session.scalar(
        select(func.count(RedirectEvent.id)).where(RedirectEvent.short_code == short_code)
    ) or 0

    # Time-series aggregation
    since = datetime.now(UTC) - timedelta(days=days)
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        trunc_expr = func.to_char(func.date_trunc(interval, RedirectEvent.occurred_at), "YYYY-MM-DD HH24:MI:SS" if interval == "hour" else "YYYY-MM-DD")
    else:
        # SQLite compatibility for testing
        format_str = "%Y-%m-%d %H:00:00" if interval == "hour" else "%Y-%m-%d"
        trunc_expr = func.strftime(format_str, RedirectEvent.occurred_at)

    ts_query = (
        select(trunc_expr.label("period"), func.count(RedirectEvent.id).label("count"))
        .where(RedirectEvent.short_code == short_code, RedirectEvent.occurred_at >= since)
        .group_by("period")
        .order_by("period")
    )
    rows = session.execute(ts_query).all()
    clicks_by_period = [
        TimeSeriesPoint(period=str(row.period), count=row.count)
        for row in rows
    ]

    # Recent raw events
    recent_rows = session.scalars(
        select(RedirectEvent)
        .where(RedirectEvent.short_code == short_code)
        .order_by(RedirectEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    recent_events = [
        RecentEventItem(event_id=ev.event_id, occurred_at=ev.occurred_at)
        for ev in recent_rows
    ]

    return UrlStatsResponse(
        short_code=url.short_code,
        original_url=url.original_url,
        total_clicks=total_clicks,
        interval=interval,
        time_range_days=days,
        clicks_by_period=clicks_by_period,
        recent_events=recent_events,
    )
