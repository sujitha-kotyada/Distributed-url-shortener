export interface User {
  id: number;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UrlItem {
  short_code: string;
  short_url: string;
  original_url: string;
  created_at: string;
}

export interface TimeSeriesPoint {
  period: string;
  count: number;
}

export interface RecentEventItem {
  event_id: string;
  occurred_at: string;
}

export interface UrlStatsResponse {
  short_code: string;
  original_url: string;
  total_clicks: number;
  interval: "hour" | "day";
  time_range_days: number;
  clicks_by_period: TimeSeriesPoint[];
  recent_events: RecentEventItem[];
}
