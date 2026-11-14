"""Live sync: the worker keeps live sources (GitHub repositories, Jira projects) up to date on a
schedule, so drift is noticed without anyone pressing "Check for changes".

Each due source gets an ordinary `source.sync` job: incremental (only what changed since the last
read) most of the time, and a full read once a day, since only a full read sees deletions.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import get_settings
from app.connectors import is_live
from app.db.models import Source, SourceStatus

log = logging.getLogger(__name__)


def _when(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def next_check(source: Source) -> datetime | None:
    """When the schedule will next read this source (None: it isn't on the schedule)."""
    hours = get_settings().live_sync_hours
    if hours <= 0 or not is_live(source.kind, source.config or {}) or source.last_synced_at is None:
        return None
    return source.last_synced_at + timedelta(hours=hours)


def schedule_due(db: Session, now: datetime | None = None) -> int:
    """Queues a sync for every live source whose last read is older than the schedule allows.
    Sources that are syncing, waiting, or failed (a broken token, say) are left alone."""
    s = get_settings()
    if s.live_sync_hours <= 0:
        return 0
    now = now or datetime.now(UTC)
    due = db.scalars(select(Source).where(
        Source.status == SourceStatus.ready,
        Source.last_synced_at < now - timedelta(hours=s.live_sync_hours),
    )).all()
    queued = 0
    for source in due:
        if not is_live(source.kind, source.config or {}):
            continue
        last_full = _when((source.config or {}).get("last_full_sync_at"))
        full = last_full is None or last_full < now - timedelta(hours=s.full_sync_hours)
        jobs.enqueue(db, "source.sync", {"source_id": source.id, "scheduled": True, **({"full": True} if full else {})})
        source.status = SourceStatus.pending
        source.status_detail = "Checking for changes (scheduled)…"
        queued += 1
    if queued:
        db.commit()
        log.info("live sync: queued %s source(s)", queued)
    return queued
