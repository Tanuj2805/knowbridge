"""Knowledge Risk Radar: which parts of the project depend on one person, and a
one-click knowledge capture (an early Gap Interview) with that person.

Admins and approvers only: it is about people, and it reads everything they
may see. Shares are computed in code from the ledger (app/radar.py).
"""

import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import audit, jobs, radar
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.db.models import Handover, HandoverStatus, User
from app.gatekeeper import policy, require
from app.schemas import CaptureIn, HandoverOut, RadarArea, RadarHolder, RadarOut, RadarPerson

router = APIRouter(prefix="/projects/{project_id}/radar", tags=["radar"])


def _area_out(a: radar.Area) -> RadarArea:
    holders = [RadarHolder(**asdict(h)) for h in a.holders]
    return RadarArea(key=a.key, name=a.name, kind=a.kind, risk=a.risk, top_share=a.top_share, summary=a.summary,
                     holders=holders, backup=RadarHolder(**asdict(a.backup)) if a.backup else None,
                     importance=a.importance, subjects=a.subjects, claim_count=len(a.claim_ids), signals=a.signals,
                     leaving=a.leaving, capture_id=a.capture_id, capture_status=a.capture_status)


@router.get("", response_model=RadarOut)
def get_radar(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    require(policy.can_start_run(p), "Only admins and approvers can see the Risk Radar.")
    r = radar.compute(db, project_id, p)
    if r.grouping:  # first look after a run: group its claims into areas in the background
        jobs.enqueue(db, "radar.areas", {"project_id": project_id})
    audit.record(db, actor_id=user.id, action="radar.view", object_type="project", object_id=project_id,
                 project_id=project_id, areas=len(r.areas))
    db.commit()
    return RadarOut(claims_ready=r.run_id is not None, areas=[_area_out(a) for a in r.areas],
                    people=[RadarPerson(**asdict(x)) for x in r.people], withheld=r.withheld,
                    grouping=r.grouping, grouped_by=r.grouped_by)


@router.post("/regroup", status_code=202)
def regroup(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB) -> dict:
    """Groups the latest run's claims into areas again (after new claims, or a failed first try)."""
    require(policy.can_start_run(p), "Only admins and approvers can regroup the Risk Radar.")
    run = radar.latest_run(db, project_id)
    if run is None:
        raise HTTPException(409, "Build claims first.")
    run.state = {k: v for k, v in (run.state or {}).items() if k != radar.STATE_KEY}
    jobs.enqueue(db, "radar.areas", {"project_id": project_id})
    audit.record(db, actor_id=user.id, action="radar.regroup", object_type="project", object_id=project_id,
                 project_id=project_id)
    db.commit()
    return {"queued": True}


@router.post("/capture", response_model=HandoverOut, status_code=201)
def start_capture(project_id: uuid.UUID, body: CaptureIn, p: ProjectPrincipal, user: CurrentUser, db: DB):
    """Starts a knowledge capture: questions about one area for the person who holds it."""
    from app.routers.handovers import _out

    require(policy.can_start_run(p), "Only admins and approvers can start a knowledge capture.")
    area = radar.area(db, project_id, p, body.area)
    if area is None:
        raise HTTPException(404, "That area isn't on the radar any more. Reload the page.")
    person_id = body.user_id or area.holders[0].user_id
    if person_id not in {h.user_id for h in area.holders}:
        raise HTTPException(422, "Pick someone who holds knowledge of this area.")
    existing = db.scalar(select(Handover).where(
        Handover.project_id == project_id, Handover.kind == radar.CAPTURE_KIND, Handover.leaver_id == person_id,
        Handover.scope["area"].astext == area.key))
    if existing is not None:
        return _out(db, existing, user.id)

    person = db.get(User, person_id)
    # The backup learns from the answers; with no backup yet, the person who asked follows up.
    backup = next((h.user_id for h in area.holders if h.user_id != person_id and h.share >= radar.BACKUP_SHARE),
                  None)
    h = Handover(project_id=project_id, kind=radar.CAPTURE_KIND, leaver_id=person_id,
                 successor_id=backup or user.id, approver_id=user.id, created_by=user.id,
                 status=HandoverStatus.drafting, title=f"Knowledge capture: {area.name} with {person.name}",
                 scope={"area": area.key, "area_name": area.name, "claim_ids": [str(c) for c in area.claim_ids],
                        "share": round(area.top_share, 3)})
    db.add(h)
    db.flush()
    jobs.enqueue(db, "interview.prepare", {"handover_id": h.id})
    audit.record(db, actor_id=user.id, action="radar.capture", object_type="handover", object_id=h.id,
                 project_id=project_id, area=area.name, person=person.name)
    db.commit()
    db.refresh(h)
    return _out(db, h, user.id)
