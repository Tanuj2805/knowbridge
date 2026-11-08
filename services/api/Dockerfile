FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# git reads repository history for the GitHub connector (no API calls needed).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
 && pip install . \
 && rm -rf app

COPY . .
RUN pip install --no-deps . \
 && useradd --create-home --uid 1000 kb \
 && mkdir -p /data/storage /data/models && chown kb /data/storage /data/models
USER kb

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
