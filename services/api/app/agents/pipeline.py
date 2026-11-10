"""One "build claims" run, as the worker carries it out: Sentinel review, Scout,
the three claim writers, then the Timeline Builder (merges duplicates, marks
replaced decisions, links conflicts) and the Skeptic (checks and grades).

Every step records its progress, so a run paused by a rate limit picks up where
it stopped (finished bundles are skipped, and answers already received come
from the cache).

The agents act with the permissions of the person who started the run.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import gatekeeper
from app.agents import evidence, extract, scout, sentinel_review, skeptic, timeline
from app.agents.base import context_for
from app.connectors.base import RetryLater
from app.db.models import Run, RunStatus
from app.llm import LLMUnavailable

log = logging.getLogger(__name__)
FINISHED = (RunStatus.done, RunStatus.failed, RunStatus.cancelled)


def reconstruct(db: Session, run_id: uuid.UUID) -> None:
    run = db.get(Run, run_id)
    if run is None or run.status in FINISHED:
        return
    run.status = RunStatus.running
    run.status_detail = ""
    run.started_at = run.started_at or datetime.now(UTC)
    db.commit()

    ctx = context_for(db, run, gatekeeper.principal(db, run.project_id, run.started_by))
    try:
        sentinel_review.review(db, ctx)
        packets = evidence.build_packets(evidence.packet_units(db, ctx.principal, run.project_id), ctx.source_names)
        routes = scout.plan(db, ctx, packets)
        for agent in extract.ALLOWED:
            extract.extract(db, ctx, agent, packets, routes)
        timeline.build(db, ctx)
        skeptic.grade(db, ctx)
        run = db.get(Run, run_id)
        run.status = RunStatus.done
        run.finished_at = datetime.now(UTC)
    except RetryLater as e:
        db.rollback()
        run = db.get(Run, run_id)
        run.status = RunStatus.queued
        run.status_detail = f"Paused: {e} It continues on its own at {e.retry_at:%H:%M} UTC."
        raise  # the job queue reschedules it without using up an attempt
    except LLMUnavailable as e:
        db.rollback()
        run = db.get(Run, run_id)
        run.status = RunStatus.failed
        run.status_detail = str(e)
        run.finished_at = datetime.now(UTC)
    except Exception as e:
        db.rollback()
        run = db.get(Run, run_id)
        run.status = RunStatus.failed
        run.status_detail = f"Stopped by an error: {e}"[:500]
        run.finished_at = datetime.now(UTC)
        raise
    finally:
        run.llm_calls = (run.llm_calls or 0) + sum(u.calls for u in ctx.usage.values())
        run.tokens_used = (run.tokens_used or 0) + sum(u.tokens for u in ctx.usage.values())
        db.commit()
