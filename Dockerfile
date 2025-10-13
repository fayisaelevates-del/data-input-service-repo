# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install system deps (if any). Keep minimal for fast builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first for better layer caching
COPY requirements.txt requirements.txt
# Optional extras can be added per-env; not installed by default
# COPY requirements-extras.txt requirements-extras.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Copy application code
COPY . .

# Cloud Run provides PORT env; default to 8080 for local
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:${PORT}/healthz || exit 1

# Run via gunicorn, pointing to wsgi:application
CMD exec gunicorn --bind 0.0.0.0:${PORT} --workers=2 --threads=4 --timeout=120 wsgi:application
