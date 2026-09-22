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

## Run Tests

```powershell
python -m pytest
```
