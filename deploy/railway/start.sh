#!/bin/sh
# Starts KnowBridge's API and its background worker in one Railway service.
set -e

mkdir -p "${STORAGE_DIR:-/data/storage}"

# bring the database schema up to date (safe to run on every start)
alembic upgrade head

# the worker runs alongside the API; if it ever stops, it starts again
(
  while true; do
    python -m app.worker || true
    echo "worker stopped; restarting in 5 s"
    sleep 5
  done
) &

# "::" listens on IPv6 and IPv4, so Railway's private network can reach the API
exec uvicorn app.main:app --host :: --port "${PORT:-8000}"
