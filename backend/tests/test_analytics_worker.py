from unittest.mock import Mock

import pytest
import redis
from redis.exceptions import ResponseError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from url_shortener.models.base import Base
from url_shortener.models.redirect_event import RedirectEvent
from url_shortener.services.analytics import (
    AnalyticsRecordingError,
    PostgresRedirectAnalytics,
    RedirectEventMessage,
)
from url_shortener.services.analytics_worker import (
    RedirectAnalyticsWorker,
    ensure_consumer_group,
)
from url_shortener.services.streams import RedisRedirectEventPublisher


class FakeRedis:
    def __init__(self, messages=None) -> None:
        self.messages = messages or []
        self.pending_messages = []
        self.acknowledged: list[str] = []
        self.group_calls: list[tuple[str, str]] = []
        self.added: list[tuple[str, dict[str, str], dict]] = []
        self.closed = False
        self.xadd_fails = False
        self.xpending_fails = False
        self.pending_info = []

    def xgroup_create(self, stream, group, id, mkstream):
        self.group_calls.append((stream, group))

    def xautoclaim(self, *args, **kwargs):
        messages, self.pending_messages = self.pending_messages, []
        return "0-0", messages

    def xreadgroup(self, *args, **kwargs):
        messages, self.messages = self.messages, []
        return [("stream", messages)] if messages else []

    def xack(self, stream, group, message_id):
        self.acknowledged.append(message_id)

    def xadd(self, stream, fields, **kwargs):
        if self.xadd_fails:
            raise redis.RedisError("DLQ write failure")
        self.added.append((stream, fields, kwargs))
        return "dlq-1"

    def xpending_range(self, *args, **kwargs):
        if self.xpending_fails:
            raise redis.RedisError("xpending network failure")
        return self.pending_info

    def close(self):
        self.closed = True


class FailingAnalytics:
    def record_event(self, *, session: Session, event) -> None:
        raise AnalyticsRecordingError("database unavailable")


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def event_fields(event_id: str = "00000000-0000-0000-0000-000000000001") -> dict[str, str]:
    return {
        "event_id": event_id,
        "short_code": "abc",
        "occurred_at": "2026-10-11T00:00:00+00:00",
    }


def make_worker(
    redis_client: FakeRedis,
    session_factory: sessionmaker[Session],
    analytics=None,
    dlq_stream_name: str = "events:dlq",
    max_retries: int = 3,
) -> RedirectAnalyticsWorker:
    return RedirectAnalyticsWorker(
        client=redis_client,
        session_factory=session_factory,
        stream_name="events",
        group_name="analytics",
        consumer_name="worker-1",
        dlq_stream_name=dlq_stream_name,
        max_retries=max_retries,
        analytics=analytics,
    )


def test_worker_persists_event_before_acknowledging(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis([("1-0", event_fields())])
    worker = make_worker(client, session_factory)

    worker.process_available()

    with session_factory() as session:
        events = session.scalars(select(RedirectEvent)).all()
    assert len(events) == 1
    assert events[0].event_id == "00000000-0000-0000-0000-000000000001"
    assert client.acknowledged == ["1-0"]


def test_worker_does_not_acknowledge_transient_failure_under_retry_limit(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis([("1-0", event_fields())])
    worker = make_worker(client, session_factory, FailingAnalytics(), max_retries=3)

    worker.process_available()

    assert client.acknowledged == []
    assert client.added == []


def test_worker_dead_letters_after_max_retries_exceeded(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    worker = make_worker(client, session_factory, FailingAnalytics(), max_retries=3)

    # Attempts 1 and 2: fail transiently
    assert worker.process_message("1-0", event_fields()) is False
    assert client.acknowledged == []
    assert client.added == []

    assert worker.process_message("1-0", event_fields()) is False
    assert client.acknowledged == []

    # Attempt 3: reaches max_retries (3), sends to DLQ and acks original message
    assert worker.process_message("1-0", event_fields()) is True
    assert client.acknowledged == ["1-0"]
    assert len(client.added) == 1
    stream, dlq_payload, _ = client.added[0]
    assert stream == "events:dlq"
    assert dlq_payload["original_id"] == "1-0"
    assert dlq_payload["attempts"] == "3"
    assert "Max retries exceeded" in dlq_payload["reason"]


def test_worker_reprocessing_event_id_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis([("1-0", event_fields()), ("2-0", event_fields())])
    analytics = PostgresRedirectAnalytics()
    with session_factory() as session:
        analytics.record_event(
            session=session,
            event=RedirectEventMessage.model_validate(event_fields()),
        )
    worker = make_worker(client, session_factory)

    worker.process_available()

    with session_factory() as session:
        assert len(session.scalars(select(RedirectEvent)).all()) == 1
    assert client.acknowledged == ["1-0", "2-0"]


def test_worker_dead_letters_malformed_message_and_acknowledges(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis([("1-0", {"short_code": "abc"})])
    worker = make_worker(client, session_factory)

    worker.process_available()

    # Poison message is sent to DLQ and acknowledged so it doesn't loop
    assert client.acknowledged == ["1-0"]
    assert len(client.added) == 1
    stream, dlq_payload, _ = client.added[0]
    assert stream == "events:dlq"
    assert dlq_payload["original_id"] == "1-0"
    assert "Validation error" in dlq_payload["reason"]


def test_worker_does_not_acknowledge_if_dlq_write_fails(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis([("1-0", {"short_code": "abc"})])
    client.xadd_fails = True
    worker = make_worker(client, session_factory)

    worker.process_available()

    # If DLQ fails, original message must NOT be acknowledged
    assert client.acknowledged == []


def test_worker_processes_pending_reclaimed_messages(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    client.pending_messages = [("reclaimed-1", event_fields("00000000-0000-0000-0000-000000000099"))]
    worker = make_worker(client, session_factory)

    worker.process_pending()

    with session_factory() as session:
        events = session.scalars(select(RedirectEvent)).all()
    assert len(events) == 1
    assert events[0].event_id == "00000000-0000-0000-0000-000000000099"
    assert client.acknowledged == ["reclaimed-1"]


def test_existing_consumer_group_is_accepted() -> None:
    client = Mock()
    client.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group exists")

    ensure_consumer_group(client, stream_name="events", group_name="analytics")

    client.xgroup_create.assert_called_once()


def test_unexpected_consumer_group_error_is_raised() -> None:
    client = Mock()
    client.xgroup_create.side_effect = ResponseError("permission denied")

    with pytest.raises(ResponseError, match="permission denied"):
        ensure_consumer_group(client, stream_name="events", group_name="analytics")


def test_worker_shutdown_stops_and_closes_resources(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    worker = make_worker(client, session_factory)

    worker.stop()
    worker.run_forever()
    worker.close()

    assert client.group_calls == [("events", "analytics")]
    assert client.closed is True


def test_stream_publisher_writes_with_maxlen_and_approximate() -> None:
    client = Mock()
    publisher = RedisRedirectEventPublisher(client, "events", max_len=50000)
    event = RedirectEventMessage.model_validate(event_fields())

    publisher.publish(event)

    client.xadd.assert_called_once_with(
        "events",
        {
            "event_id": str(event.event_id),
            "short_code": "abc",
            "occurred_at": "2026-10-11T00:00:00+00:00",
        },
        maxlen=50000,
        approximate=True,
    )


def test_worker_retries_resilient_to_restart_via_xpending(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    # Message already attempted twice before worker restart according to Redis PEL
    msg_id = "00000000-0000-0000-0000-000000000001"
    client.pending_info = [
        {
            "message_id": msg_id,
            "consumer": "worker-1",
            "time_since_delivered": 5000,
            "times_delivered": 2,
        }
    ]

    # New worker instance after restart (fresh in-memory dictionary) with max_retries=2
    worker = make_worker(client, session_factory, analytics=FailingAnalytics(), max_retries=2)
    assert msg_id not in worker._retry_counts

    # Process message: even on attempt 1 in this new process, delivery count 2 meets max_retries
    processed = worker.process_message(msg_id, event_fields())

    # Should dead-letter immediately based on Redis PEL delivery count
    assert processed is True
    assert client.acknowledged == [msg_id]
    assert len(client.added) == 1
    stream, fields, _ = client.added[0]
    assert stream == "events:dlq"
    assert fields["original_id"] == msg_id
    assert fields["attempts"] == "2"
    assert "Max retries exceeded" in fields["reason"]


def test_worker_xpending_failure_falls_back_to_local_retry_count(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    client.xpending_fails = True
    msg_id = "00000000-0000-0000-0000-000000000002"

    worker = make_worker(client, session_factory, analytics=FailingAnalytics(), max_retries=2)

    # First attempt: xpending_range fails, falls back to local count 1 < 2 -> no DLQ, no ACK
    assert worker.process_message(msg_id, event_fields()) is False
    assert client.acknowledged == []
    assert client.added == []

    # Second attempt: local count reaches 2 -> dead-letters successfully
    assert worker.process_message(msg_id, event_fields()) is True
    assert client.acknowledged == [msg_id]
    assert len(client.added) == 1