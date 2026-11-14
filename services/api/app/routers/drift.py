"""Live sync and drift: the log of what changed at the sources and what it did to the claims,
and (demo mode) a way to make such a change by hand."""

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app import drift, gatekeeper
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.config import get_settings
from app.db.models import Claim, ClaimDrift, ClaimEvidence, EvidenceUnit, Source, User
from app.gatekeeper import policy, require
from app.schemas import DriftOut, DriftPage, SimulateChangeIn

router = APIRouter(prefix="/projects/{project_id}", tags=["drift"])


def drift_out(d: ClaimDrift, claim: Claim | None = None, unit: EvidenceUnit | None = None, source_name: str = "",
              resolved_by: str = "") -> DriftOut:
    return DriftOut(
        id=d.id, claim_id=d.claim_id, claim_statement=claim.statement if claim else "",
        claim_status=claim.status if claim else None, evidence_id=d.evidence_id,
        evidence_title=unit.title if unit else "", source_name=source_name, change=d.change, outcome=d.outcome,
        outcome_text=drift.OUTCOME_TEXT.get(d.outcome, d.outcome), quote=d.quote, before=d.before, after=d.after,
        note=d.note, grade_before=d.grade_before, grade_after=d.grade_after, reopened=d.reopened,
        simulated=d.simulated, detected_at=d.detected_at, checked_at=d.checked_at, resolved_at=d.resolved_at,
        resolved_by_name=resolved_by,
    )


def _visible_claims(db: DB, p, project_id: uuid.UUID, claim_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Claims whose every cited item this person may see (the ledger's rule)."""
    if not claim_ids:
        return set()
    cites = db.execute(select(ClaimEvidence.claim_id, ClaimEvidence.evidence_id)
                       .where(ClaimEvidence.claim_id.in_(claim_ids))).all()
    visible = gatekeeper.visible_evidence_ids(db, p, project_id, [e for _, e in cites])
    blocked = {c for c, e in cites if e not in visible}
    return {c for c, _ in cites} - blocked


@router.get("/drift", response_model=DriftPage)
def drift_log(project_id: uuid.UUID, p: ProjectPrincipal, db: DB, limit: int = Query(default=30, ge=1, le=200),
              everything: bool = Query(default=False, alias="all")):
    """Recent changes at the sources that touched claims, newest first. all=true also lists the
    changes where the quoted words were untouched (logged, nothing to do)."""
    require(policy.can_view_ledger(p), "Only admins and approvers can see what changed.")
    q = select(ClaimDrift).where(ClaimDrift.project_id == project_id)
    if not everything:
        q = q.where(ClaimDrift.outcome != "quote_intact")
    rows = db.scalars(q.order_by(ClaimDrift.detected_at.desc()).limit(limit * 3)).all()
    allowed = _visible_claims(db, p, project_id, {d.claim_id for d in rows})
    rows = [d for d in rows if d.claim_id in allowed][:limit]
    claims = {c.id: c for c in db.scalars(select(Claim).where(Claim.id.in_({d.claim_id for d in rows})))}
    units = {u.id: u for u in db.scalars(select(EvidenceUnit).where(
        EvidenceUnit.id.in_({d.evidence_id for d in rows if d.evidence_id})))}
    names = dict(db.execute(select(Source.id, Source.name).where(Source.project_id == project_id)).all())
    people = dict(db.execute(select(User.id, User.name).where(
        User.id.in_({d.resolved_by for d in rows if d.resolved_by}))).all())

    open_ids = set(db.scalars(select(Claim.id).where(Claim.project_id == project_id, Claim.source_changed.is_(True))))
    checking = db.scalar(select(func.count()).select_from(ClaimDrift).where(
        ClaimDrift.project_id == project_id, ClaimDrift.outcome == "pending")) or 0
    return DriftPage(
        sync_every_hours=get_settings().live_sync_hours,
        open=len(_visible_claims(db, p, project_id, open_ids)),
        checking=checking,
        items=[drift_out(d, claims.get(d.claim_id), units.get(d.evidence_id), names.get(d.source_id, ""),
                         people.get(d.resolved_by, "")) for d in rows],
        can_simulate=get_settings().demo_mode and policy.can_manage_project(p),
    )


@router.post("/evidence/{evidence_id}/simulate-change")
def simulate_change(project_id: uuid.UUID, evidence_id: uuid.UUID, body: SimulateChangeIn, p: ProjectPrincipal,
                    user: CurrentUser, db: DB) -> dict:
    """Demo mode: edit an item as if it had changed in its tool, to show drift detection live."""
    if not get_settings().demo_mode:
        raise HTTPException(404, "Not found.")
    require(policy.can_manage_project(p), "Only a project admin can simulate a source change.")
    unit = db.get(EvidenceUnit, evidence_id)
    if unit is None or unit.project_id != project_id or (unit.meta or {}).get("removed_at") \
            or evidence_id not in gatekeeper.visible_evidence_ids(db, p, project_id, [evidence_id]):
        raise HTTPException(404, "Evidence not found.")
    if body.text.strip() == unit.text.strip():
        raise HTTPException(422, "Nothing changed: edit the text first.")
    return {"claims": drift.simulate(db, unit, body.text, user)}
