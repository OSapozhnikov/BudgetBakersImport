FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATA_DIR=/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN mkdir -p /data \
    && groupadd --system bbi \
    && useradd --system --gid bbi --home-dir /app --shell /usr/sbin/nologin bbi \
    && chown -R bbi:bbi /app /data \
    && chmod +x /docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# Entrypoint runs as root only long enough to fix /data permissions, then drops to bbi.
ENTRYPOINT ["/docker-entrypoint.sh"]
# WEB_CONCURRENCY must stay 1: conversion jobs are in-memory and not shared across workers.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-1}"]
