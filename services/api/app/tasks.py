"""Job handlers. Imported by the worker so they register themselves."""

import uuid

from sqlalchemy.orm import Session

from app import ingest
from app.jobs import handler


@handler("source.sync")
def sync_source(db: Session, payload: dict) -> None:
    ingest.sync_source(db, uuid.UUID(payload["source_id"]), full=bool(payload.get("full")))


@handler("project.embed")
def embed_project(db: Session, payload: dict) -> None:
    """Indexes one quota-sized portion and reschedules itself until the project is done."""
    ingest.embed_with_quota(db, uuid.UUID(payload["project_id"]))
