from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TimeSeriesPoint(BaseModel):
    period: str
    count: int


class RecentEventItem(BaseModel):
    event_id: str
    occurred_at: datetime


class UrlStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    short_code: str
    original_url: str
    total_clicks: int
    interval: Literal["hour", "day"]
    time_range_days: int
    clicks_by_period: list[TimeSeriesPoint]
    recent_events: list[RecentEventItem]
