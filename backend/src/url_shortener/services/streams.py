import redis

from url_shortener.core.config import Settings
from url_shortener.services.analytics import (
    RedirectEventMessage,
    RedirectEventPublisher,
)


class AnalyticsPublishError(RuntimeError):
    """Raised when a redirect event cannot be published to Redis Streams."""


class RedisRedirectEventPublisher(RedirectEventPublisher):
    def __init__(
        self,
        client: redis.Redis,
        stream_name: str,
        max_len: int = 100000,
    ) -> None:
        self._client = client
        self._stream_name = stream_name
        self._max_len = max_len

    def publish(self, event: RedirectEventMessage) -> None:
        try:
            self._client.xadd(
                self._stream_name,
                {
                    "event_id": str(event.event_id),
                    "short_code": event.short_code,
                    "occurred_at": event.occurred_at.isoformat(),
                },
                maxlen=self._max_len,
                approximate=True,
            )
        except redis.RedisError as exc:
            raise AnalyticsPublishError("Redis stream publish failed.") from exc

    def close(self) -> None:
        self._client.close()


def create_event_publisher(settings: Settings) -> RedisRedirectEventPublisher | None:
    if settings.redis_url is None:
        return None
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
    )
    return RedisRedirectEventPublisher(
        client,
        settings.analytics_stream_name,
        max_len=settings.analytics_stream_maxlen,
    )