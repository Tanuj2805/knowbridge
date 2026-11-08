"""A small job queue on Postgres (SELECT … FOR UPDATE SKIP LOCKED).

Enough for one or a few workers, no extra service to run. Handlers are plain
functions registered by name.
"""

import logging
import os
import socket
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, JobStatus

log = logging.getLogger(__name__)

Handler = Callable[[Session, dict], None]
HANDLERS: dict[str, Handler] = {}
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


def enqueue(
    db: Session, kind: str, payload: dict, *, dedupe: bool = True, run_after: datetime | None = None
) -> Job:
    """Add a job. With dedupe, an identical job that hasn't started yet is reused."""
    payload = {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in payload.items()}
    if dedupe:
        existing = db.scalar(
            select(Job).where(Job.kind == kind, Job.status == JobStatus.queued, Job.payload == payload)
        )
        if existing:
            return existing
    job = Job(kind=kind, payload=payload, **({"run_after": run_after} if run_after else {}))
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session) -> Job | None:
    job = db.scalar(
        select(Job)
        .where(Job.status == JobStatus.queued, Job.run_after <= datetime.now(UTC))
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.running
    job.locked_by = WORKER_ID
    job.attempts += 1
    db.commit()
    return job


def run(db: Session, job: Job) -> None:
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {job.kind!r}")
        fn(db, job.payload)
        job = db.get(Job, job.id)
        job.status = JobStatus.done
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.get(Job, job.id)
        job.last_error = f"{type(e).__name__}: {e}"[:2000]
        from app.connectors import ConnectorError, RetryLater

        if isinstance(e, RetryLater):
            # Rate limited: not a failure, so it doesn't use up an attempt.
            job.status = JobStatus.queued
            job.attempts -= 1
            job.run_after = e.retry_at
            db.commit()
            log.info("job %s paused until %s: %s", job.id, e.retry_at.isoformat(), e)
            return
        if isinstance(e, ConnectorError) or job.attempts >= job.max_attempts:
            job.status = JobStatus.failed
            job.finished_at = datetime.now(UTC)
        else:
            job.status = JobStatus.queued
            job.run_after = datetime.now(UTC) + timedelta(seconds=15 * 2 ** job.attempts)
        db.commit()
        log.exception("job %s (%s) failed on attempt %s", job.id, job.kind, job.attempts)


def requeue_orphaned(db: Session) -> int:
    """On start-up: jobs left 'running' by an earlier worker process on this host
    (a restart keeps the hostname but not the pid) go back in the queue."""
    host = WORKER_ID.rsplit(":", 1)[0]
    stale = db.scalars(
        select(Job).where(
            Job.status == JobStatus.running,
            Job.locked_by.like(f"{host}:%"),
            Job.locked_by != WORKER_ID,
        )
    ).all()
    for job in stale:
        job.status = JobStatus.queued
        job.locked_by = None
    db.commit()
    return len(stale)
