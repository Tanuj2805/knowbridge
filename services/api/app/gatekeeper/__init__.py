"""Gatekeeper: decides who may see what. Rule-based, never a model.

Every read of evidence goes through `visible_evidence_clause` (a SQL filter
built from the rules in policy.py). With AUTHZ_BACKEND=openfga, results are
then confirmed by OpenFGA as well, so a bug in either one alone cannot leak.
"""

import uuid
from collections import Counter
from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, any_, false, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Claim,
    ClaimEvidence,
    EvidenceUnit,
    Membership,
    Project,
    Role,
    Sensitivity,
    Source,
)
from app.gatekeeper import openfga
from app.gatekeeper.openfga import TupleKey
from app.gatekeeper.policy import Principal, can_view_evidence, cleared_for
from app.sentinel import strictest

_LABEL_TEXT = {
    Sensitivity.restricted: "Restricted",
    Sensitivity.confidential: "Confidential",
    Sensitivity.team: "Team",
}


def _fga_enabled() -> bool:
    return get_settings().authz_backend == "openfga"


# --- principals ---------------------------------------------------------


def principal(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> Principal:
    rows = db.execute(
        select(Membership.role, Membership.clearances).where(
            Membership.project_id == project_id, Membership.user_id == user_id
        )
    ).all()
    return Principal(
        user_id=user_id,
        roles=frozenset(r.role for r in rows),
        clearances=frozenset(c for r in rows for c in (r.clearances or [])),
    )


def require(allowed: bool, message: str = "You don't have access to this.") -> None:
    if not allowed:
        raise HTTPException(status_code=403, detail=message)


# --- evidence -----------------------------------------------------------


def visible_evidence_clause(p: Principal) -> ColumnElement[bool]:
    """SQL condition on EvidenceUnit (joined to Source) matching policy.can_view_evidence."""
    if not p.is_member:
        return false()
    source_ok = or_(
        func.cardinality(Source.readers) == 0,
        p.user_id == any_(Source.readers),
    )
    allowed_labels = [s for s in Sensitivity if cleared_for(p, s)]
    return and_(source_ok, EvidenceUnit.sensitivity.in_(allowed_labels))


def visible_evidence_ids(
    db: Session, p: Principal, project_id: uuid.UUID, evidence_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    ids = list(set(evidence_ids))
    if not ids or not p.is_member:
        return set()
    rows = db.execute(
        select(EvidenceUnit.id, EvidenceUnit.sensitivity, Source.readers)
        .join(Source, Source.id == EvidenceUnit.source_id)
        .where(EvidenceUnit.project_id == project_id, EvidenceUnit.id.in_(ids))
    ).all()
    allowed = {r.id for r in rows if can_view_evidence(p, r.readers or [], r.sensitivity)}
    if allowed and _fga_enabled():
        fga = openfga.client()
        fga.ensure_ready(db)
        ordered = sorted(allowed)
        verdicts = fga.batch_check(
            [TupleKey(f"user:{p.user_id}", "viewer", f"evidence:{i}") for i in ordered]
        )
        allowed = {i for i, ok in zip(ordered, verdicts, strict=True) if ok}
    return allowed


# --- claims -------------------------------------------------------------


class ClaimFilter:
    """Splits claims into what a reader may see and what is withheld.

    A claim is visible only if the reader can see *every* piece of evidence
    behind it, and is cleared for the claim's own label.
    """

    def __init__(self, db: Session, p: Principal, project_id: uuid.UUID) -> None:
        self.db, self.p, self.project_id = db, p, project_id

    def split(self, claims: list[Claim]) -> tuple[list[Claim], Counter[str]]:
        claim_ids = [c.id for c in claims]
        links = self.db.execute(
            select(ClaimEvidence.claim_id, ClaimEvidence.evidence_id).where(
                ClaimEvidence.claim_id.in_(claim_ids)
            )
        ).all()
        by_claim: dict[uuid.UUID, set[uuid.UUID]] = {}
        for link in links:
            by_claim.setdefault(link.claim_id, set()).add(link.evidence_id)
        all_ids = {e for ids in by_claim.values() for e in ids}
        visible_ids = visible_evidence_ids(self.db, self.p, self.project_id, all_ids)

        visible: list[Claim] = []
        withheld: Counter[str] = Counter()
        for c in claims:
            needed = by_claim.get(c.id, set())
            if cleared_for(self.p, c.sensitivity) and needed <= visible_ids:
                visible.append(c)
            else:
                withheld[_LABEL_TEXT[c.sensitivity]] += 1
        return visible, withheld


def claim_sensitivity(db: Session, claim_id: uuid.UUID) -> Sensitivity:
    """A claim takes the strictest label of its sources."""
    labels = db.scalars(
        select(EvidenceUnit.sensitivity)
        .join(ClaimEvidence, ClaimEvidence.evidence_id == EvidenceUnit.id)
        .where(ClaimEvidence.claim_id == claim_id)
    ).all()
    return strictest(*labels) if labels else Sensitivity.team


# --- keeping OpenFGA in step with Postgres ------------------------------


def _label_obj(project_id: uuid.UUID, s: Sensitivity) -> str:
    return f"label:{project_id}-{s.value}"


def sync_project(db: Session, project_id: uuid.UUID) -> None:
    """Rewrite the membership and label tuples for a project from Postgres."""
    if not _fga_enabled():
        return
    fga = openfga.client()
    fga.ensure_ready(db)
    project = db.get(Project, project_id)
    if project is None:
        return
    proj = f"project:{project_id}"
    members = db.scalars(select(Membership).where(Membership.project_id == project_id)).all()

    writes = [
        TupleKey(f"user:{m.user_id}", m.role.value, proj) for m in members
    ] + [
        TupleKey(f"{proj}#member", "cleared", _label_obj(project_id, Sensitivity.team)),
        TupleKey(f"{proj}#admin", "cleared", _label_obj(project_id, Sensitivity.restricted)),
        TupleKey(f"{proj}#approver", "cleared", _label_obj(project_id, Sensitivity.restricted)),
    ]
    for m in members:
        cl = set(m.clearances or [])
        if cl & {"restricted", "confidential"}:
            writes.append(
                TupleKey(f"user:{m.user_id}", "cleared", _label_obj(project_id, Sensitivity.restricted))
            )
        if "confidential" in cl:
            writes.append(
                TupleKey(
                    f"user:{m.user_id}", "cleared", _label_obj(project_id, Sensitivity.confidential)
                )
            )
    fga.write(writes)


def revoke_membership(db: Session, m: Membership) -> None:
    if not _fga_enabled():
        return
    fga = openfga.client()
    fga.ensure_ready(db)
    proj = f"project:{m.project_id}"
    deletes = [TupleKey(f"user:{m.user_id}", m.role.value, proj)]
    for s in (Sensitivity.restricted, Sensitivity.confidential):
        deletes.append(TupleKey(f"user:{m.user_id}", "cleared", _label_obj(m.project_id, s)))
    fga.write(deletes=deletes)
    # Clearances shared by another remaining membership row are re-added.
    sync_project(db, m.project_id)


def sync_source(db: Session, source: Source, previous_readers: list[uuid.UUID] | None = None) -> None:
    if not _fga_enabled():
        return
    fga = openfga.client()
    fga.ensure_ready(db)
    obj = f"source:{source.id}"
    proj = f"project:{source.project_id}"

    def readers_of(readers: list[uuid.UUID]) -> list[TupleKey]:
        if not readers:
            return [TupleKey(f"{proj}#member", "reader", obj)]
        return [TupleKey(f"user:{u}", "reader", obj) for u in readers]

    deletes = readers_of(previous_readers) if previous_readers is not None else []
    writes = [TupleKey(proj, "project", obj), *readers_of(source.readers or [])]
    fga.write(writes=writes, deletes=[d for d in deletes if d not in writes])


def sync_evidence(db: Session, units: list[EvidenceUnit]) -> None:
    if not _fga_enabled() or not units:
        return
    fga = openfga.client()
    fga.ensure_ready(db)
    writes: list[TupleKey] = []
    for u in units:
        obj = f"evidence:{u.id}"
        writes.append(TupleKey(f"source:{u.source_id}", "source", obj))
        writes.append(TupleKey(_label_obj(u.project_id, u.sensitivity), "label", obj))
    fga.write(writes)


def relabel_evidence(db: Session, unit: EvidenceUnit, old: Sensitivity) -> None:
    if not _fga_enabled() or old == unit.sensitivity:
        return
    fga = openfga.client()
    fga.ensure_ready(db)
    obj = f"evidence:{unit.id}"
    fga.write(
        writes=[TupleKey(_label_obj(unit.project_id, unit.sensitivity), "label", obj)],
        deletes=[TupleKey(_label_obj(unit.project_id, old), "label", obj)],
    )


__all__ = [
    "ClaimFilter",
    "Principal",
    "Role",
    "claim_sensitivity",
    "principal",
    "relabel_evidence",
    "require",
    "revoke_membership",
    "sync_evidence",
    "sync_project",
    "sync_source",
    "visible_evidence_clause",
    "visible_evidence_ids",
]
