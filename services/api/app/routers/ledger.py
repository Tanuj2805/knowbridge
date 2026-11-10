"""Runs ("build claims") and the claim ledger they produce.

A claim is shown only when the viewer can see every item it cites, so a claim
never reveals evidence the viewer isn't cleared for.
"""

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app import audit, gatekeeper, jobs, llm, rag, retrieval
from app.agents.facts import SYSTEM_DATA
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    ClaimVersion,
    EvidenceUnit,
    Grade,
    Run,
    RunStatus,
    Source,
    User,
)
from app.gatekeeper import policy, require
from app.schemas import (
    BulkReview,
    ClaimCite,
    ClaimOut,
    ClaimRef,
    ClaimReview,
    LedgerPage,
    RunOut,
    RunStepOut,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["ledger"])
ACTIVE = (RunStatus.queued, RunStatus.running)
AGENTS = ("decision_miner", "ownership_mapper", "risk_detector")
_FILLED = {"evidence", "from_system_data", "checked", "skeptic_note", "replaces", "replaced_by", "conflicts",
           "reviewed_by_name"}
APPROVED = (ClaimStatus.approved, ClaimStatus.edited)
EVIDENCE_HITS = 20  # evidence results a claim search looks through

log = logging.getLogger(__name__)


def _run_out(db: DB, run: Run) -> RunOut:
    out = RunOut.model_validate(run)
    progress = (run.state or {}).get("progress", {})
    out.steps = [RunStepOut.model_validate(s).model_copy(update={"progress": progress.get(s.agent)})
                 for s in run.steps]
    if run.started_by:
        out.started_by_name = db.scalar(select(User.name).where(User.id == run.started_by)) or ""
    return out


def _latest(db: DB, project_id: uuid.UUID) -> Run | None:
    return db.scalars(select(Run).where(Run.project_id == project_id, Run.kind == "reconstruct")
                      .order_by(Run.created_at.desc()).limit(1)).first()


@router.post("/runs", response_model=RunOut, status_code=202)
def start_run(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    """Builds a fresh draft ledger from the project's evidence."""
    require(policy.can_start_run(p), "Only admins and approvers can build claims.")
    if not llm.configured():
        raise HTTPException(409, "No AI model is set up. Add GEMINI_API_KEY, or LLM_BASE_URL and LLM_API_KEY, to .env.")
    current = _latest(db, project_id)
    if current and current.status in ACTIVE:
        raise HTTPException(409, "A run is already in progress.")
    if not db.scalar(select(func.count()).select_from(EvidenceUnit).where(EvidenceUnit.project_id == project_id)):
        raise HTTPException(409, "Connect a source first: there is no evidence to read yet.")
    run = Run(project_id=project_id, kind="reconstruct", status=RunStatus.queued, started_by=user.id)
    db.add(run)
    db.flush()
    jobs.enqueue(db, "run.reconstruct", {"run_id": run.id}, dedupe=False)
    audit.record(db, actor_id=user.id, action="run.start", object_type="run", object_id=run.id,
                 project_id=project_id)
    db.commit()
    db.refresh(run)
    return _run_out(db, run)


@router.get("/runs/latest", response_model=RunOut | None)
def latest_run(project_id: uuid.UUID, p: ProjectPrincipal, db: DB):
    require(policy.can_view_ledger(p), "Only admins and approvers can see runs.")
    run = _latest(db, project_id)
    return _run_out(db, run) if run else None


@router.get("/claims", response_model=LedgerPage)
def list_claims(
    project_id: uuid.UUID,
    p: ProjectPrincipal,
    db: DB,
    type: ClaimType | None = None,  # noqa: A002 - the API's word for it
    grade: Grade | None = None,
    agent: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=200),
    show: str | None = Query(default=None, pattern="^(removed)$"),
    review: str | None = Query(default=None, pattern="^(todo|approved)$"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """The latest run's current claims: high impact first, then newest evidence. Claims a
    later one replaced appear under it; claims the Skeptic removed are listed with show=removed.
    `limit`/`offset` page through the matches; `total` says how many there are."""
    require(policy.can_view_ledger(p), "Only admins and approvers can see the claim ledger.")
    run = _latest(db, project_id)
    if run is None:
        return LedgerPage(run=None, llm_ready=llm.configured(), items=[], counts={}, hidden=0)

    claims = db.scalars(select(Claim).where(Claim.run_id == run.id)).all()
    cites = db.execute(
        select(ClaimEvidence, EvidenceUnit, Source.name)
        .join(EvidenceUnit, EvidenceUnit.id == ClaimEvidence.evidence_id)
        .join(Source, Source.id == EvidenceUnit.source_id)
        .where(ClaimEvidence.claim_id.in_([c.id for c in claims]))
    ).all()
    visible = gatekeeper.visible_evidence_ids(db, p, project_id, [u.id for _, u, _ in cites])
    by_claim: dict[uuid.UUID, list[tuple[ClaimEvidence, EvidenceUnit, str]]] = {}
    for ce, u, source_name in cites:
        by_claim.setdefault(ce.claim_id, []).append((ce, u, source_name))

    allowed = [c for c in claims if by_claim.get(c.id) and all(u.id in visible for _, u, _ in by_claim[c.id])]
    hidden = len(claims) - len(allowed)
    by_id = {c.id: c for c in allowed}
    removed = [c for c in allowed if c.status == ClaimStatus.rejected]
    current = [c for c in allowed if c.status != ClaimStatus.rejected and c.superseded_by not in by_id]
    counts = Counter(c.type.value for c in current)
    grades = Counter(c.grade.value for c in current if _checked(c, run))

    review_counts = {"todo": sum(1 for c in current if c.status == ClaimStatus.draft),
                     "approved": sum(1 for c in current if c.status in APPROVED)}
    shown = removed if show == "removed" else current
    if review == "todo":
        shown = [c for c in shown if c.status == ClaimStatus.draft]
    elif review == "approved":
        shown = [c for c in shown if c.status in APPROVED]
    if type:
        shown = [c for c in shown if c.type == type]
    if grade:
        shown = [c for c in shown if c.grade == grade and _checked(c, run)]
    if agent in AGENTS:
        shown = [c for c in shown if c.created_by_agent == agent]
    searching = bool(q and q.strip())
    if searching:
        shown = _search_claims(db, p, project_id, q.strip(), shown, by_claim)

    def newest(c: Claim):
        return max((u.occurred_at for _, u, _ in by_claim[c.id] if u.occurred_at), default=c.created_at)

    matching = len(shown)
    if not searching:  # a search keeps its best-match-first order
        shown = sorted(shown, key=lambda c: (c.impact, newest(c)), reverse=True)  # high impact, then newest
    shown = shown[offset:offset + limit] if limit else shown[offset:]
    reviewers = {u.id: u.name for u in db.scalars(select(User).where(
        User.id.in_({c.reviewed_by for c in shown if c.reviewed_by})))}
    items = []
    for c in shown:
        out = ClaimOut.model_validate({k: getattr(c, k) for k in ClaimOut.model_fields if k not in _FILLED})
        out.from_system_data = c.grade_reason.startswith(SYSTEM_DATA)
        out.checked = _checked(c, run)
        out.reviewed_by_name = reviewers.get(c.reviewed_by, "")
        out.skeptic_note = (c.skeptic or {}).get("note", "")
        out.replaces = [_ref(o) for o in allowed if o.superseded_by == c.id and o.status != ClaimStatus.rejected]
        out.replaced_by = _ref(by_id[c.superseded_by]) if c.superseded_by in by_id else None
        out.conflicts = [_ref(by_id[o]) for o in (c.conflicts_with or [])
                         if o in by_id and by_id[o].status != ClaimStatus.rejected]
        out.evidence = [
            ClaimCite(evidence_id=u.id, quote=ce.quote, kind=u.kind, title=u.title, locator=u.locator,
                      author=u.author, occurred_at=u.occurred_at, permalink=u.permalink, source_name=source_name)
            for ce, u, source_name in sorted(by_claim[c.id], key=lambda t: t[1].occurred_at or c.created_at)
        ]
        items.append(out)
    return LedgerPage(run=_run_out(db, run), llm_ready=llm.configured(), items=items, total=matching,
                      counts=dict(counts),
                      grades=dict(grades), replaced=sum(1 for c in allowed if c.superseded_by in by_id
                                                        and c.status != ClaimStatus.rejected),
                      removed=len(removed), hidden=hidden, review=review_counts, can_review=policy.can_review(p))


def _search_claims(db: DB, p, project_id: uuid.UUID, query: str, claims: list[Claim],
                   by_claim: dict) -> list[Claim]:
    """Claims for a search, best first. A claim matches on its own words (statement, subject, owner,
    reason and its quotes, filler words like "why" dropped), or because the project's evidence search
    (by meaning, where smart search is on) finds the evidence it rests on."""
    terms = retrieval.query_terms(query)
    text_score: dict[uuid.UUID, float] = {}
    for c in claims:
        quotes = " ".join(ce.quote for ce, _, _ in by_claim.get(c.id, []))
        found = retrieval.word_hits(terms, f"{c.statement} {c.subject} {c.owner_name} {c.rationale} {quotes}")
        if terms and found:
            text_score[c.id] = found / len(terms)

    evidence_score: dict[uuid.UUID, float] = {}
    try:
        hits = retrieval.search(db, p, project_id, query, limit=EVIDENCE_HITS)
    except Exception:  # noqa: BLE001 - search by meaning is a bonus; words alone still work
        log.warning("evidence search failed for a claim search", exc_info=True)
        hits = []
    for rank, h in enumerate(hits):
        weight = (1.0 if h.strength == "strong" else 0.4) * (1 - rank / (2 * len(hits)))
        for unit in [h.unit, *(r.unit for r in h.related)]:
            evidence_score[unit.id] = max(evidence_score.get(unit.id, 0), weight)

    scored = []
    for c in claims:
        via_evidence = max((evidence_score.get(u.id, 0) for _, u, _ in by_claim.get(c.id, [])), default=0)
        score = text_score.get(c.id, 0) + via_evidence
        # half the words, or evidence the search is fairly sure of
        if text_score.get(c.id, 0) >= 0.5 or via_evidence >= 0.4:
            scored.append((score, c))
    return [c for _, c in sorted(scored, key=lambda sc: sc[0], reverse=True)]


def _checked(c: Claim, run: Run) -> bool:
    """Graded by the Skeptic (system-data claims count once the Skeptic step has run)."""
    if c.skeptic:
        return True
    return c.grade_reason.startswith(SYSTEM_DATA) and any(s.agent == "skeptic" and s.status == "done"
                                                          for s in run.steps)


def _ref(c: Claim) -> ClaimRef:
    return ClaimRef(id=c.id, statement=c.statement, valid_from=c.valid_from, valid_to=c.valid_to, grade=c.grade)


# --- review: an approver approves, edits or rejects each claim ----------------


def _reviewable(db: DB, p, project_id: uuid.UUID, claim_id: uuid.UUID) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.project_id != project_id:
        raise HTTPException(404, "Claim not found.")
    cited = [ce.evidence_id for ce in claim.evidence]
    if not cited or set(cited) - gatekeeper.visible_evidence_ids(db, p, project_id, cited):
        raise HTTPException(404, "Claim not found.")  # cites something this reviewer can't see
    return claim


def _review(db: DB, claim: Claim, user: User, action: str, body: ClaimReview | None = None) -> None:
    """Applies one review action, keeping the previous wording as a version."""
    db.add(ClaimVersion(claim_id=claim.id, version=claim.version, statement=claim.statement, status=claim.status,
                        grade=claim.grade, note=body.note if body else "", edited_by=user.id))
    if action == "approve":
        claim.status = ClaimStatus.approved
    elif action == "reject":
        claim.status = ClaimStatus.rejected
    elif action == "reopen":
        claim.status = ClaimStatus.draft
    else:  # edit: the reviewer's wording becomes the claim, which counts as approved
        assert body is not None
        for field in ("statement", "rationale", "owner_name", "due_date"):
            value = getattr(body, field)
            if value is not None:
                setattr(claim, field, value.strip() if isinstance(value, str) else value)
        claim.status = ClaimStatus.edited
        rag.forget_vector(claim)  # its meaning changed: re-made in the background
        jobs.enqueue(db, "rag.index", {"project_id": claim.project_id})
    claim.version += 1
    claim.reviewed_by, claim.reviewed_at = user.id, datetime.now(UTC)
    claim.review_note = (body.note.strip() if body else "") or (claim.review_note if action == "edit" else "")
    audit.record(db, actor_id=user.id, action=f"claim.{action}", object_type="claim", object_id=claim.id,
                 project_id=claim.project_id, version=claim.version)


@router.patch("/claims/{claim_id}", status_code=204)
def review_claim(project_id: uuid.UUID, claim_id: uuid.UUID, body: ClaimReview, p: ProjectPrincipal,
                 user: CurrentUser, db: DB) -> None:
    require(policy.can_review(p), "Only an approver can review claims.")
    claim = _reviewable(db, p, project_id, claim_id)
    if body.action == "edit" and not any(getattr(body, f) is not None
                                         for f in ("statement", "rationale", "owner_name", "due_date")):
        raise HTTPException(422, "Nothing to change.")
    _review(db, claim, user, body.action, body)
    db.commit()


@router.post("/claims/review", status_code=200)
def approve_many(project_id: uuid.UUID, body: BulkReview, p: ProjectPrincipal, user: CurrentUser, db: DB) -> dict:
    """Approves drafts in bulk: the listed ids, every current draft with one of the listed grades, or
    (all=true) every current draft the reviewer can see."""
    require(policy.can_review(p), "Only an approver can review claims.")
    run = _latest(db, project_id)
    if run is None:
        return {"approved": 0}
    claims = db.scalars(select(Claim).where(Claim.run_id == run.id, Claim.status == ClaimStatus.draft)).all()
    ids = set(db.scalars(select(Claim.id).where(Claim.run_id == run.id)))
    wanted = [c for c in claims if c.superseded_by not in ids
              and (body.all or c.id in set(body.ids) or (c.grade in set(body.grades) and _checked(c, run)))]
    cited = [ce.evidence_id for c in wanted for ce in c.evidence]
    visible = gatekeeper.visible_evidence_ids(db, p, project_id, cited)
    done = 0
    for c in wanted:
        if c.evidence and all(ce.evidence_id in visible for ce in c.evidence):
            _review(db, c, user, "approve")
            done += 1
    db.commit()
    return {"approved": done}

