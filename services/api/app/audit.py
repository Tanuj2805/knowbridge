import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str,
    object_id: uuid.UUID | str,
    project_id: uuid.UUID | None = None,
    **meta: object,
) -> None:
    """Append to the audit log. The caller commits."""
    db.add(
        AuditEvent(
            project_id=project_id,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            meta={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in meta.items()},
        )
    )
