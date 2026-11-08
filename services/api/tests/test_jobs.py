"""The job queue: retries, and rate-limit pauses that don't count as failures."""

from datetime import UTC, datetime, timedelta

import pytest

from app import jobs
from app.connectors import ConnectorError, RetryLater
from app.db.models import Job, JobStatus

pytestmark = pytest.mark.db


@pytest.fixture
def handlers(monkeypatch):
    calls = []
    retry_at = datetime.now(UTC) + timedelta(minutes=30)

    def limited(db, payload):
        calls.append("limited")
        raise RetryLater("GitHub's rate limit was reached.", retry_at)

    def broken_input(db, payload):
        raise ConnectorError("bad file")

    def crash(db, payload):
        raise RuntimeError("boom")

    monkeypatch.setitem(jobs.HANDLERS, "test.limited", limited)
    monkeypatch.setitem(jobs.HANDLERS, "test.bad", broken_input)
    monkeypatch.setitem(jobs.HANDLERS, "test.crash", crash)
    return retry_at


def _run(db, kind):
    job = jobs.enqueue(db, kind, {"n": kind}, dedupe=False)
    db.commit()
    job.status, job.attempts = JobStatus.running, 1
    db.commit()
    jobs.run(db, job)
    return db.get(Job, job.id)


def test_rate_limit_requeues_without_using_an_attempt(db, handlers):
    job = _run(db, "test.limited")
    assert job.status == JobStatus.queued and job.attempts == 0
    assert abs((job.run_after - handlers).total_seconds()) < 1


def test_bad_input_fails_without_retrying(db, handlers):
    assert _run(db, "test.bad").status == JobStatus.failed


def test_crash_is_retried_with_backoff(db, handlers):
    job = _run(db, "test.crash")
    assert job.status == JobStatus.queued and job.run_after > datetime.now(UTC)
