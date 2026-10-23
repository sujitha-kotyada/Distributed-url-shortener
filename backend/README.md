# Distributed URL Shortener Backend

Backend foundation for the Distributed URL Shortener & Analytics Platform.

## Requirements

- Python 3.13+
- PostgreSQL

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the backend with development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Copy the example environment file when local overrides are needed:

```powershell
Copy-Item .env.example .env
```

Configure `DATABASE_URL` in `.env` with a PostgreSQL connection string:

```text
DATABASE_URL=postgresql+psycopg://url_shortener:change-me@localhost:5432/url_shortener
```

## Database Migrations

Apply migrations:

```powershell
python -m alembic upgrade head
```

Create a new migration after model changes:

```powershell
python -m alembic revision --autogenerate -m "describe change"
```

## Run The API

```powershell
python -m uvicorn url_shortener.main:app --app-dir src --reload
```

The health endpoint is available at:

```text
GET /health
GET /health/db
```

The database health check returns `503 Service Unavailable` when `DATABASE_URL`
is missing or PostgreSQL cannot be reached.

## Redirect Analytics

Each successful redirect records one `redirect_events` row with the resolved
URL's stable `short_code` and a server-generated UTC `occurred_at` timestamp.
Unknown short codes and health or URL creation requests do not create events.

The redirect API publishes a minimal event containing `event_id`, `short_code`,
and `occurred_at` to the configured Redis Stream. A separate worker consumes
that stream through a Redis consumer group and persists the event. The worker
acknowledges a message only after the PostgreSQL commit succeeds. Pending
messages can be reclaimed after the configured idle period, and the unique
event ID makes reprocessing idempotent.

Configure `REDIS_URL`, `ANALYTICS_STREAM_NAME`, `ANALYTICS_CONSUMER_GROUP`,
`ANALYTICS_CONSUMER_NAME`, `ANALYTICS_READ_BLOCK_MS`, `ANALYTICS_BATCH_SIZE`,
and `ANALYTICS_CLAIM_IDLE_MS` in `.env`. Run the worker separately from the API:

```powershell
$env:PYTHONPATH="src"
python -m url_shortener.services.analytics_worker
```

Publishing is best effort: if Redis is unavailable, the redirect still returns
307 but that event can be lost. Processing is at-least-once rather than
exactly-once; idempotency prevents duplicate rows after redelivery. There is
no live Redis verification in this development environment when Redis is not
running, and no background worker is started inside the API process.

## Run Tests

```powershell
python -m pytest
```
