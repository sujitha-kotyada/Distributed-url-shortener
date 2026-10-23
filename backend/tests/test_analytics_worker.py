import threading
import time
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
from url_shortener.core.config import Settings
from url_shortener.services.analytics_worker import (
    RedirectAnalyticsWorker,
    create_worker,
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


def test_create_worker_configures_dedicated_worker_socket_timeout(
    session_factory: sessionmaker[Session],
) -> None:
    settings = Settings(
        redis_url="redis://localhost:6379/0",
        redis_socket_timeout_seconds=0.5,
        redis_socket_connect_timeout_seconds=0.75,
        analytics_socket_timeout_seconds=5.0,
        analytics_read_block_ms=1000,
    )
    worker = create_worker(settings, session_factory=session_factory)
    try:
        pool_kwargs = worker._client.connection_pool.connection_kwargs
        assert pool_kwargs["socket_timeout"] == 5.0
        assert pool_kwargs["socket_connect_timeout"] == 0.75
        assert pool_kwargs["decode_responses"] is True
        assert worker._read_block_ms == 1000
    finally:
        worker.close()


def test_worker_run_forever_recovers_from_transient_redis_timeout(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    call_count = 0

    def fail_once_then_stop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        worker.stop()
        raise redis.exceptions.TimeoutError("Timeout reading from socket")

    client.xreadgroup = fail_once_then_stop
    worker = make_worker(client, session_factory)

    # run_forever should catch TimeoutError, log warning, check stop_requested, and return cleanly
    worker.run_forever(poll_timeout_backoff_seconds=0.01)

    assert call_count == 1
    assert worker._stop_requested.is_set()


def test_worker_run_forever_recovers_from_transient_redis_connection_error(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    call_count = 0

    def fail_once_then_stop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        worker.stop()
        raise redis.exceptions.ConnectionError("Connection closed by remote host")

    client.xreadgroup = fail_once_then_stop
    worker = make_worker(client, session_factory)

    worker.run_forever(poll_timeout_backoff_seconds=0.01)

    assert call_count == 1
    assert worker._stop_requested.is_set()


def test_worker_run_forever_surfaces_unrecoverable_redis_error(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()

    def fail_with_response_error(*args, **kwargs):
        raise ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")

    client.xreadgroup = fail_with_response_error
    worker = make_worker(client, session_factory)

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        worker.run_forever(poll_timeout_backoff_seconds=0.01)


def test_worker_run_forever_recovers_from_repeated_failures_then_processes(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    attempts = 0

    def fail_twice_then_deliver(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise redis.exceptions.TimeoutError("Temporary socket timeout")
        worker.stop()
        return [("events", [("3-0", event_fields("00000000-0000-0000-0000-000000000077"))])]

    client.xreadgroup = fail_twice_then_deliver
    worker = make_worker(client, session_factory)

    worker.run_forever(poll_timeout_backoff_seconds=0.01)

    assert attempts == 3
    with session_factory() as session:
        events = session.scalars(select(RedirectEvent)).all()
    assert len(events) == 1
    assert events[0].event_id == "00000000-0000-0000-0000-000000000077"
    assert client.acknowledged == ["3-0"]


def test_worker_responsive_shutdown_during_backoff(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()

    def always_timeout(*args, **kwargs):
        raise redis.exceptions.TimeoutError("Timeout reading from socket")

    client.xreadgroup = always_timeout
    worker = make_worker(client, session_factory)

    # Signal stop 0.05 seconds after starting a 5-second backoff
    timer = threading.Timer(0.05, worker.stop)
    timer.start()

    start_time = time.monotonic()
    worker.run_forever(poll_timeout_backoff_seconds=5.0)
    elapsed = time.monotonic() - start_time
    timer.cancel()

    # Must exit promptly upon stop signal, well before the 5.0-second backoff expires
    assert elapsed < 1.0
    assert worker._stop_requested.is_set()


def test_worker_idle_blocking_read_exceeds_old_timeout(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    read_called = False

    def slow_idle_read(*args, **kwargs):
        nonlocal read_called
        read_called = True
        worker.stop()
        # Simulate idle stream where Redis server blocks for 0.6s (longer than old 0.5s timeout)
        time.sleep(0.6)
        return []

    client.xreadgroup = slow_idle_read
    worker = make_worker(client, session_factory)

    start_time = time.monotonic()
    worker.run_forever(poll_timeout_backoff_seconds=0.01)
    elapsed = time.monotonic() - start_time

    assert read_called is True
    assert elapsed >= 0.55


def test_worker_pending_recovery_persists_across_transient_failure(
    session_factory: sessionmaker[Session],
) -> None:
    client = FakeRedis()
    autoclaim_attempts = 0

    def fail_once_then_autoclaim(*args, **kwargs):
        nonlocal autoclaim_attempts
        autoclaim_attempts += 1
        if autoclaim_attempts == 1:
            raise redis.exceptions.ConnectionError("Redis connection dropped")
        # On second attempt, claim pending message
        worker.stop()
        return "0-0", [("reclaimed-2", event_fields("00000000-0000-0000-0000-000000000088"))]

    client.xautoclaim = fail_once_then_autoclaim
    worker = make_worker(client, session_factory)

    worker.run_forever(poll_timeout_backoff_seconds=0.01)

    assert autoclaim_attempts == 2
    with session_factory() as session:
        events = session.scalars(select(RedirectEvent)).all()
    assert len(events) == 1
    assert events[0].event_id == "00000000-0000-0000-0000-000000000088"
    assert client.acknowledged == ["reclaimed-2"]


def test_worker_increments_processed_metric_on_successful_event(
    session_factory: sessionmaker[Session],
) -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    client = FakeRedis([("msg-1", event_fields("00000000-0000-0000-0000-000000000099"))])
    collector = PrometheusMetricsCollector()
    worker = RedirectAnalyticsWorker(
        client=client,
        session_factory=session_factory,
        stream_name="events",
        group_name="analytics",
        consumer_name="worker-1",
        metrics=collector,
    )

    worker.process_available()

    assert collector.worker_processed_total == 1
    assert collector.worker_failed_total == 0
    assert collector.worker_dead_lettered_total == 0
    assert client.acknowledged == ["msg-1"]


def test_worker_increments_failed_and_dlq_metrics(
    session_factory: sessionmaker[Session],
) -> None:
    from url_shortener.core.metrics import PrometheusMetricsCollector

    client = FakeRedis()
    collector = PrometheusMetricsCollector()
    worker = RedirectAnalyticsWorker(
        client=client,
        session_factory=session_factory,
        stream_name="events",
        group_name="analytics",
        consumer_name="worker-1",
        analytics=FailingAnalytics(),
        max_retries=2,
        metrics=collector,
    )

    fields = event_fields("00000000-0000-0000-0000-000000000077")
    res1 = worker.process_message("fail-1", fields)
    assert res1 is False
    assert collector.worker_failed_total == 1
    assert collector.worker_dead_lettered_total == 0

    res2 = worker.process_message("fail-1", fields)
    assert res2 is True
    assert collector.worker_failed_total == 2
    assert collector.worker_dead_lettered_total == 1
    assert len(client.added) == 1


def test_worker_metrics_server_lifecycle_and_endpoints() -> None:
    import urllib.request
    from url_shortener.core.metrics import PrometheusMetricsCollector
    from url_shortener.services.analytics_worker import WorkerMetricsServer

    collector = PrometheusMetricsCollector()
    collector.increment_worker_processed()
    collector.increment_worker_processed()

    server = WorkerMetricsServer(host="127.0.0.1", port=0, collector=collector)
    port = server.server.server_port
    server.start()

    try:
        metrics_url = f"http://127.0.0.1:{port}/metrics"
        with urllib.request.urlopen(metrics_url) as resp:
            assert resp.status == 200
            assert "text/plain" in resp.headers["content-type"]
            body = resp.read().decode("utf-8")
            assert "url_shortener_worker_processed_total 2" in body

        health_url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(health_url) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers["content-type"]
            body = resp.read().decode("utf-8")
            assert '"status":"ok"' in body
    finally:
        server.stop()