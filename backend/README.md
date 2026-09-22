# Distributed URL Shortener Backend

Backend foundation for the Distributed URL Shortener & Analytics Platform.

## Requirements

- Python 3.13+

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

## Run The API

```powershell
python -m uvicorn url_shortener.main:app --app-dir src --reload
```

The health endpoint is available at:

```text
GET /health
```

## Run Tests

```powershell
python -m pytest
```
