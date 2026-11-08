"""Load the synthetic Project Nimbus demo (data/nimbus) into a fresh project.

CLI:  python -m app.seed nimbus [--reset] [--no-sync]
API:  POST /demo/nimbus  (DEMO_MODE only)
"""

import uuid
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, gatekeeper, jobs, storage
from app.config import get_settings
from app.db.models import Membership, Project, Role, Sensitivity, Source, SourceKind, User


def _data_dir() -> Path:
    return get_settings().data_dir / "nimbus"


def load_manifest() -> dict:
    path = _data_dir() / "manifest.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Demo data not found at {path}. Set DATA_DIR to the repo's data/ folder.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def create_nimbus(db: Session, created_by: uuid.UUID | None = None, *, enqueue: bool = True) -> Project:
    """Create a new Project Nimbus with its people and sources. Sources are
    synced by the worker (enqueue=True) or by the caller."""
    m = load_manifest()
    root = _data_dir()

    users: dict[str, User] = {}
    for person in m["people"]:
        user = db.scalar(select(User).where(User.email == person["email"]))
        if user is None:
            user = User(email=person["email"], name=person["name"], auth_provider="demo")
            db.add(user)
            db.flush()
        users[person["key"]] = user

    base_name = m["project"]["name"]
    existing = db.scalars(select(Project.name).where(Project.name.like(f"{base_name}%"))).all()
    name = base_name if base_name not in existing else f"{base_name} ({len(existing) + 1})"
    from app.routers.projects import _slugify

    project = Project(name=name, slug=_slugify(db, name), description=m["project"]["description"].strip(),
                      created_by=created_by or users["kabir"].id)
    db.add(project)
    db.flush()

    for person in m["people"]:
        for role in person["roles"]:
            db.add(Membership(project_id=project.id, user_id=users[person["key"]].id, role=Role(role),
                              role_template=person.get("role_template"),
                              clearances=person.get("clearances", [])))
    # Whoever loads the demo can see it, as an admin.
    if created_by and created_by not in {u.id for u in users.values()}:
        db.add(Membership(project_id=project.id, user_id=created_by, role=Role.admin))
    db.flush()

    for spec in m["sources"]:
        source = Source(
            project_id=project.id,
            kind=SourceKind(spec["kind"]),
            name=spec["name"],
            default_sensitivity=Sensitivity(spec.get("sensitivity", "team")),
            readers=[users[k].id for k in spec.get("readers", [])],
            created_by=project.created_by,
            config={"demo_key": spec["key"]},
        )
        db.add(source)
        db.flush()
        stored = []
        for pattern in spec["files"]:
            matches = sorted(root.glob(pattern))
            if not matches:
                raise FileNotFoundError(f"Demo file missing: {root / pattern}")
            for path in matches:
                storage.save_upload(project.id, source.id, path.name, path.read_bytes())
                stored.append(path.name)
        source.config = {**source.config, "files": stored}
        if enqueue:
            jobs.enqueue(db, "source.sync", {"source_id": source.id})

    audit.record(db, actor_id=created_by, action="project.demo_load", object_type="project",
                 object_id=project.id, project_id=project.id)
    db.commit()
    gatekeeper.sync_project(db, project.id)
    for source in db.scalars(select(Source).where(Source.project_id == project.id)):
        gatekeeper.sync_source(db, source)
    return project
