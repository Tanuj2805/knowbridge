"""Job handlers. Imported by the worker so they register themselves."""

import uuid

from sqlalchemy.orm import Session

from app import ingest, jobs
from app.db.models import GapQuestion, Handover, Run, RunStatus
from app.jobs import handler


def _index_later(db: Session, project_id) -> None:
    """Claims changed: make their meaning vectors for "Ask the project" (only missing ones)."""
    jobs.enqueue(db, "rag.index", {"project_id": project_id})
    db.commit()


@handler("source.sync")
def sync_source(db: Session, payload: dict) -> None:
    ingest.sync_source(db, uuid.UUID(payload["source_id"]), full=bool(payload.get("full")))


@handler("project.embed")
def embed_project(db: Session, payload: dict) -> None:
    """Indexes one quota-sized portion and reschedules itself until the project is done."""
    ingest.embed_with_quota(db, uuid.UUID(payload["project_id"]))


@handler("run.reconstruct")
def reconstruct(db: Session, payload: dict) -> None:
    """Sentinel review, Scout and the claim writers for one run; resumes after a pause."""
    from app.agents import pipeline

    run_id = uuid.UUID(payload["run_id"])
    pipeline.reconstruct(db, run_id)
    run = db.get(Run, run_id)
    if run is not None and run.status == RunStatus.done:
        _index_later(db, run.project_id)


@handler("interview.prepare")
def prepare_interview(db: Session, payload: dict) -> None:
    """The Gap Interviewer writes a handover's questions."""
    from app.agents import interviewer

    interviewer.prepare(db, uuid.UUID(payload["handover_id"]))


@handler("interview.answer")
def apply_interview_answer(db: Session, payload: dict) -> None:
    """Reads one answer and updates the ledger (re-grades, settles conflicts)."""
    from app.agents import interviewer

    question_id = uuid.UUID(payload["question_id"])
    interviewer.apply_answer(db, question_id)
    q = db.get(GapQuestion, question_id)
    handover = db.get(Handover, q.handover_id) if q is not None else None
    if handover is not None:
        _index_later(db, handover.project_id)


@handler("handover.compose")
def compose_pack(db: Session, payload: dict) -> None:
    """The Composer writes a new version of a handover pack and its 30-day plan."""
    from app.agents import composer

    composer.compose(db, uuid.UUID(payload["handover_id"]))


@handler("rag.index")
def index_claims(db: Session, payload: dict) -> None:
    """Meaning vectors for the latest claims, for "Ask the project"; paced by the provider's quota."""
    from app import rag

    rag.index_claims(db, uuid.UUID(payload["project_id"]))
