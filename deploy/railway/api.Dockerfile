# The API and the worker for Railway, in one service (built from the repository root).
#
# Why one service: uploaded source files live on a volume, and a Railway volume belongs to one
# service; the API saves uploads and the worker reads them. Running both here also costs less.
# Runs as root because Railway mounts volumes as root. The Nimbus demo data is copied in, so
# "Load the demo" works.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# git reads repository history for the GitHub connector (no API calls needed).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# dependencies first, so code changes rebuild in seconds
COPY services/api/pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
 && pip install . \
 && rm -rf app

COPY services/api/ .
RUN pip install --no-deps .
COPY data/ /srv/data/
COPY deploy/railway/start.sh /start.sh
RUN chmod +x /start.sh && mkdir -p /data/storage /data/models

ENV DATA_DIR=/srv/data \
    STORAGE_DIR=/data/storage \
    MODEL_CACHE_DIR=/data/models

EXPOSE 8000
CMD ["/start.sh"]
