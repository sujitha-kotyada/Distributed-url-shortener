import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Event

import redis
from pydantic import ValidationError
from redis.exceptions import ResponseError

from url_shortener.core.config import Settings
from url_shortener.core.database import create_session_factory
from url_shortener.services.analytics import (
    AnalyticsRecordingError,
    PostgresRedirectAnalytics,
    RedirectEventMessage,
)


logger = logging.getLogger(__name__)


def ensure_consumer_group(
    client: redis.Redis,
    *,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        client.xgroup_create(stream_name, group_name, id="0-0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


class RedirectAnalyticsWorker:
    def __init__(
        self,
        *,
        client: redis.Redis,
        session_factory,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        dlq_stream_name: str = "url_shortener:redirect_events:dlq",
        max_retries: int = 3,
        read_block_ms: int = 1000,
        batch_size: int = 10,
        claim_idle_ms: int = 60000,
        analytics: PostgresRedirectAnalytics | None = None,
    ) -> None:
        self._client = client
        self._session_factory = session_factory
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._dlq_stream_name = dlq_stream_name
        self._max_retries = max_retries
        self._read_block_ms = read_block_ms
        self._batch_size = batch_size
        self._claim_idle_ms = claim_idle_ms
        self._analytics = analytics or PostgresRedirectAnalytics()
        self._stop_requested = Event()
        self._retry_counts: dict[str, int] = {}

    def stop(self) -> None:
        self._stop_requested.set()

    def close(self) -> None:
        self._client.close()

    def _dead_letter(
        self,
        message_id: str,
        fields: dict[str, str],
        *,
        reason: str,
        attempts: int,
    ) -> bool:
        """Publish an unprocessable message to the DLQ and acknowledge it from the main stream."""
        try:
            self._client.xadd(
                self._dlq_stream_name,
                {
                    "original_id": message_id,
                    "short_code": str(fields.get("short_code", "")),
                    "payload": json.dumps(fields),
                    "reason": reason,
                    "attempts": str(attempts),
                    "dead_lettered_at": datetime.now(UTC).isoformat(),
                },
            )
        except redis.RedisError:
            logger.error("Failed to write message %s to DLQ stream %s.", message_id, self._dlq_stream_name)
            return False

        try:
            self._client.xack(self._stream_name, self._group_name, message_id)
        except redis.RedisError:
            logger.warning("Failed to acknowledge dead-lettered message %s.", message_id)
            return False

        self._retry_counts.pop(message_id, None)
        return True

    def _get_delivery_count(self, message_id: str) -> int:
        """Query Redis Streams pending entries list (PEL) to obtain persistent delivery attempt count."""
        try:
            pending = self._client.xpending_range(
                self._stream_name,
                self._group_name,
                min=message_id,
                max=message_id,
                count=1,
            )
            if pending and isinstance(pending, list):
                first = pending[0]
                if isinstance(first, dict) and "times_delivered" in first:
                    return int(first["times_delivered"])
        except (redis.RedisError, AttributeError) as exc:
            logger.debug("Could not retrieve pending delivery count for message %s: %s", message_id, exc)
        return 0

    def process_message(self, message_id: str, fields: dict[str, str]) -> bool:
        try:
            event = RedirectEventMessage.model_validate(fields)
        except ValidationError as exc:
            logger.warning("Permanent validation error in redirect analytics event %s: %s", message_id, exc)
            return self._dead_letter(
                message_id,
                fields,
                reason=f"Validation error: {exc}",
                attempts=1,
            )

        try:
            with self._session_factory() as session:
                self._analytics.record_event(session=session, event=event)
        except AnalyticsRecordingError as exc:
            local_attempts = self._retry_counts.get(message_id, 0) + 1
            self._retry_counts[message_id] = local_attempts
            redis_delivery_count = self._get_delivery_count(message_id)
            attempts = max(local_attempts, redis_delivery_count)

            if attempts >= self._max_retries:
                logger.warning(
                    "Max retries (%d) exceeded for event %s (attempts: %d). Dead-lettering.",
                    self._max_retries,
                    message_id,
                    attempts,
                )
                return self._dead_letter(
                    message_id,
                    fields,
                    reason=f"Max retries exceeded: {exc}",
                    attempts=attempts,
                )
            logger.warning(
                "Redirect analytics event processing failed (attempt %d/%d).",
                attempts,
                self._max_retries,
            )
            return False

        try:
            self._client.xack(self._stream_name, self._group_name, message_id)
        except redis.RedisError:
            logger.warning("Redirect analytics acknowledgement failed.")
            return False

        self._retry_counts.pop(message_id, None)
        return True

    def _process_messages(
        self,
        messages: Iterable[tuple[str, dict[str, str]]],
    ) -> None:
        for message_id, fields in messages:
            self.process_message(message_id, fields)

    def process_pending(self) -> None:
        claimed = self._client.xautoclaim(
            self._stream_name,
            self._group_name,
            self._consumer_name,
            min_idle_time=self._claim_idle_ms,
            start_id="0-0",
            count=self._batch_size,
        )
        self._process_messages(claimed[1])

    def process_available(self) -> None:
        response = self._client.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: ">"},
            count=self._batch_size,
            block=self._read_block_ms,
        )
        for _, messages in response:
            self._process_messages(messages)

    def run_forever(self) -> None:
        ensure_consumer_group(
            self._client,
            stream_name=self._stream_name,
            group_name=self._group_name,
        )
        while not self._stop_requested.is_set():
            self.process_pending()
            if not self._stop_requested.is_set():
                self.process_available()


def create_worker(settings: Settings) -> RedirectAnalyticsWorker:
    if settings.redis_url is None:
        raise RuntimeError("REDIS_URL must be set to run the analytics worker.")
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
    )
    return RedirectAnalyticsWorker(
        client=client,
        session_factory=create_session_factory(),
        stream_name=settings.analytics_stream_name,
        group_name=settings.analytics_consumer_group,
        consumer_name=settings.analytics_consumer_name,
        dlq_stream_name=settings.analytics_dlq_stream_name,
        max_retries=settings.analytics_max_retries,
        read_block_ms=settings.analytics_read_block_ms,
        batch_size=settings.analytics_batch_size,
        claim_idle_ms=settings.analytics_claim_idle_ms,
    )


def main() -> None:
    from url_shortener.core.config import get_settings
    from url_shortener.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)
    worker = create_worker(settings)
    try:
        worker.run_forever()
    except (KeyboardInterrupt, SystemExit):
        worker.stop()
    finally:
        worker.close()


if __name__ == "__main__":
    main()