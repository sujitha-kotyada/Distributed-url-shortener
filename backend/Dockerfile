FROM python:3.13-slim

WORKDIR /app

# Prevent Python from writing .pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Install system dependencies needed for compiling C extensions if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and source code
COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src

# Install package dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8000

# Default command runs the FastAPI server
CMD ["uvicorn", "url_shortener.main:app", "--host", "0.0.0.0", "--port", "8000"]
