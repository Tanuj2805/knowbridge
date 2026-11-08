import re
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select

from app import audit, gatekeeper
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.db.models import (
    AuditEvent,
    Claim,
    EvidenceUnit,
    Membership,
    Project,
    Role,
    Source,
    User,
)
from app.gatekeeper import policy, require
from app.schemas import MemberOut, MemberUpsert, ProjectCreate, ProjectSummary, UserOut

router = APIRouter(prefix="/projects", tags=["projects"])

CLEARANCES = {"restricted", "confidential"}


def _slugify(db: DB, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "project"
    slug, n = base, 2
    while db.scalar(select(Project.id).where(Project.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _summary(db: DB, project: Project, user_id: uuid.UUID) -> ProjectSummary:
    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    roles = db.scalars(
        select(Membership.role).where(
            Membership.project_id == project.id, Membership.user_id == user_id
        )
    ).all()
    return ProjectSummary(
        **{k: getattr(project, k) for k in ProjectSummary.model_fields if hasattr(project, k)},
        my_roles=sorted(set(roles), key=lambda r: list(Role).index(r)),
        member_count=db.scalar(
            select(func.count(func.distinct(Membership.user_id))).where(
                Membership.project_id == project.id
            )
        )
        or 0,
        source_count=count(Source, Source.project_id == project.id),
        evidence_count=count(EvidenceUnit, EvidenceUnit.project_id == project.id),
        claim_count=count(Claim, Claim.project_id == project.id),
    )


@router.get("", response_model=list[ProjectSummary])
def list_projects(user: CurrentUser, db: DB):
    projects = db.scalars(
        select(Project)
        .join(Membership, Membership.project_id == Project.id)
        .where(Membership.user_id == user.id)
        .distinct()
        .order_by(Project.created_at.desc())
    ).all()
    return [_summary(db, p, user.id) for p in projects]


@router.post("", response_model=ProjectSummary, status_code=201)
def create_project(body: ProjectCreate, user: CurrentUser, db: DB):
    project = Project(
        name=body.name.strip(),
        slug=_slugify(db, body.name),
        description=body.description.strip(),
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    db.add(Membership(project_id=project.id, user_id=user.id, role=Role.admin))
    audit.record(
        db, actor_id=user.id, action="project.create", object_type="project",
        object_id=project.id, project_id=project.id,
    )
    db.commit()
    gatekeeper.sync_project(db, project.id)
    return _summary(db, project, user.id)


@router.get("/{project_id}", response_model=ProjectSummary)
def get_project(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    return _summary(db, project, user.id)


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: uuid.UUID, p: ProjectPrincipal, db: DB):
    rows = db.scalars(
        select(Membership).where(Membership.project_id == project_id).order_by(Membership.created_at)
    ).all()
    grouped: dict[uuid.UUID, MemberOut] = {}
    for m in rows:
        out = grouped.setdefault(
            m.user_id,
            MemberOut(user=UserOut.model_validate(m.user), roles=[], clearances=[]),
        )
        out.roles.append(m.role)
        out.role_template = out.role_template or m.role_template
        out.clearances = sorted(set(out.clearances) | set(m.clearances or []))
    return list(grouped.values())


@router.put("/{project_id}/members", response_model=MemberOut)
def upsert_member(
    project_id: uuid.UUID, body: MemberUpsert, p: ProjectPrincipal, user: CurrentUser, db: DB
):
    require(policy.can_manage_project(p), "Only a project admin can change members.")
    bad = set(body.clearances) - CLEARANCES
    if bad:
        raise HTTPException(422, f"Unknown clearance: {', '.join(sorted(bad))}")

    email = body.email.strip().lower()
    member = db.scalar(select(User).where(User.email == email))
    if member is None:
        member = User(email=email, name=body.name or email.split("@")[0], auth_provider="invite")
        db.add(member)
        db.flush()

    existing = db.scalars(
        select(Membership).where(
            Membership.project_id == project_id, Membership.user_id == member.id
        )
    ).all()
    if member.id == user.id and Role.admin not in body.roles:
        raise HTTPException(422, "You can't remove your own admin role.")
    for m in existing:
        if m.role not in body.roles:
            gatekeeper.revoke_membership(db, m)
            db.delete(m)
    have = {m.role for m in existing}
    for role in body.roles:
        if role not in have:
            db.add(Membership(project_id=project_id, user_id=member.id, role=role))
    db.flush()
    for m in db.scalars(
        select(Membership).where(
            Membership.project_id == project_id, Membership.user_id == member.id
        )
    ):
        m.role_template = body.role_template
        m.clearances = sorted(set(body.clearances))
    audit.record(
        db, actor_id=user.id, action="member.upsert", object_type="user", object_id=member.id,
        project_id=project_id, roles=[r.value for r in body.roles], clearances=body.clearances,
    )
    db.commit()
    gatekeeper.sync_project(db, project_id)
    return MemberOut(
        user=UserOut.model_validate(member),
        roles=list(body.roles),
        role_template=body.role_template,
        clearances=sorted(set(body.clearances)),
    )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: uuid.UUID, user_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB
):
    require(policy.can_manage_project(p), "Only a project admin can change members.")
    if user_id == user.id:
        raise HTTPException(422, "You can't remove yourself.")
    for m in db.scalars(
        select(Membership).where(Membership.project_id == project_id, Membership.user_id == user_id)
    ):
        gatekeeper.revoke_membership(db, m)
    db.execute(
        delete(Membership).where(Membership.project_id == project_id, Membership.user_id == user_id)
    )
    audit.record(
        db, actor_id=user.id, action="member.remove", object_type="user", object_id=user_id,
        project_id=project_id,
    )
    db.commit()


@router.get("/{project_id}/audit")
def list_audit(project_id: uuid.UUID, p: ProjectPrincipal, db: DB, limit: int = 100, before: str | None = None):
    require(policy.can_view_ledger(p), "Only admins and approvers can see the audit log.")
    q = (
        select(AuditEvent, User.name)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .where(AuditEvent.project_id == project_id)
        .order_by(AuditEvent.at.desc())
        .limit(min(limit, 500))
    )
    if before:
        q = q.where(AuditEvent.at < before)
    return [
        {
            "id": e.id,
            "at": e.at,
            "actor": name,
            "action": e.action,
            "object_type": e.object_type,
            "object_id": e.object_id,
            "meta": e.meta,
        }
        for e, name in db.execute(q).all()
    ]
