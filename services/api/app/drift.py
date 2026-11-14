"""Drift: what happens to claims when the evidence they cite changes at its source.

Every sync (scheduled, manual, or a re-upload) compares each changed item with what it said before:

  1. Code first. If the words a claim quotes are still in the new text, the claim still stands on
     them: the change is logged ("quote_intact") and nothing else happens. No model call.
  2. If the quoted words changed, the Skeptic re-reads the claim against the item's new text and
     says again whether it supports, partly supports, contradicts or no longer mentions it.
  3. If the item was deleted at the source, the claim loses that support (no model needed).

Grades are then recomputed by code (`skeptic.regrade`). A claim whose support weakened, whose grade
moved, or whose source vanished goes back to the approver's review queue, so it drops out of the next
handover pack until a person approves it again. The published pack is a snapshot and never changes
under its reader; it shows "changed since you read it" next to the affected lines instead.

Each event is kept in `claim_drifts` with the passage before and after the change.
"""

import difflib
import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import audit, jobs, llm
from app.db.models import (
    Claim,
    ClaimDrift,
    ClaimEvidence,
    ClaimStatus,
    ClaimVersion,
    EvidenceUnit,
    Run,
    RunStatus,
    Source,
    User,
)

log = logging.getLogger(__name__)

CHECK_BATCH = 30  # claims re-checked per job; the rest follow in the next one
WINDOW = 240  # characters of context kept around the quote, before and after
APPROVED = (ClaimStatus.approved, ClaimStatus.edited)
JUDGED = {"supports", "partial", "contradicts", "unrelated"}
WEAKER = {"partial", "contradicts", "unrelated", "removed", "needs_person"}

OUTCOME_TEXT = {
    "quote_intact": "the quoted words are unchanged",
    "pending": "being re-checked",
    "supports": "the new text still backs it",
    "partial": "the new text backs only part of it",
    "contradicts": "the new text says otherwise",
    "unrelated": "the new text no longer says this",
    "removed": "the item was deleted at the source",
    "needs_person": "a person needs to re-read it",
}


# --- text helpers ---------------------------------------------------------------


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def quote_present(quote: str, text: str) -> bool:
    """The quoted words still appear (ignoring case and spacing)."""
    q = _flat(quote).lower()
    return bool(q) and q in _flat(text).lower()


def passages(quote: str, old: str, new: str) -> tuple[str, str]:
    """The part of the old text around the quote, and the matching part of the new text."""
    old_f, new_f = _flat(old), _flat(new)
    at = old_f.lower().find(_flat(quote).lower()[:60]) if quote else -1
    if at < 0:
        at = 0
    a, b = max(0, at - WINDOW), min(len(old_f), at + len(_flat(quote)) + WINDOW)
    before = old_f[a:b]
    if not new_f:
        return before, ""
    # where the same stretch landed in the new text
    ops = difflib.SequenceMatcher(None, old_f, new_f, autojunk=False).get_opcodes()

    def mapped(i: int) -> int:
        for tag, i1, i2, j1, _j2 in ops:
            if i < i2 or i == i1 == i2:
                return j1 + (i - i1) if tag == "equal" else j1
        return len(new_f)

    a2, b2 = mapped(a), max(mapped(b), mapped(a) + 1)
    after = new_f[a2 : min(len(new_f), b2 + WINDOW // 4)]
    return ("… " if a else "") + before + (" …" if b < len(old_f) else ""), \
        ("… " if a2 else "") + after + (" …" if b2 + WINDOW // 4 < len(new_f) else "")


# --- detecting --------------------------------------------------------------------


def _latest_run_id(db: Session, project_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(select(Run.id).where(Run.project_id == project_id, Run.kind == "reconstruct",
                                          Run.status == RunStatus.done).order_by(Run.created_at.desc()).limit(1))


def _live_claims(db: Session, project_id: uuid.UUID):
    """The claims that matter: the latest run's current ones (and any made outside a run)."""
    run_id = _latest_run_id(db, project_id)
    where = [Claim.project_id == project_id, Claim.status != ClaimStatus.rejected, Claim.superseded_by.is_(None)]
    where.append(or_(Claim.run_id.is_(None), Claim.run_id == run_id) if run_id else Claim.run_id.is_(None))
    return where


def detect(
    db: Session,
    source: Source,
    changed: list[tuple[EvidenceUnit, str, bool]],
    removed: list[EvidenceUnit],
    *,
    simulated: bool = False,
) -> int:
    """Logs what the changes mean for the claims citing them. `changed` holds (item as it is now,
    its old "title\\ntext", whether it was deleted before and is back). Returns how many claims need
    another look; their re-check by the Skeptic is queued."""
    before: dict[uuid.UUID, tuple[EvidenceUnit, str, str]] = {}
    for unit, old, restored in changed:
        before[unit.id] = (unit, old, "restored" if restored else "changed")
    for unit in removed:
        before[unit.id] = (unit, f"{unit.title}\n{unit.text}", "removed")
    if not before:
        return 0

    cites = db.execute(
        select(ClaimEvidence, Claim).join(Claim, Claim.id == ClaimEvidence.claim_id)
        .where(ClaimEvidence.evidence_id.in_(list(before)), *_live_claims(db, source.project_id))
    ).all()
    if not cites:
        return 0
    # (claim, item) pairs the Skeptic has re-judged before: their stance came from a drift check, so
    # finding the old quote again (a change undone) still needs a fresh look.
    rejudged = set(db.execute(select(ClaimDrift.claim_id, ClaimDrift.evidence_id).where(
        ClaimDrift.claim_id.in_({c.id for _, c in cites}), ClaimDrift.outcome.not_in(["quote_intact"]))).all())

    now = datetime.now(UTC)
    attention: set[uuid.UUID] = set()
    recheck = False
    gone: dict[uuid.UUID, list[ClaimDrift]] = defaultdict(list)
    for ce, claim in cites:
        unit, old, change = before[ce.evidence_id]
        new = "" if change == "removed" else f"{unit.title}\n{unit.text}"
        was, now_text = passages(ce.quote, old, new)
        d = ClaimDrift(project_id=source.project_id, claim_id=claim.id, evidence_id=unit.id, source_id=source.id,
                       change=change, quote=ce.quote[:1000], before=was, after=now_text, stance_before=ce.stance,
                       grade_before=claim.grade.value, simulated=simulated)
        if change == "removed":
            d.outcome = "removed"
            ce.stance = "removed"
            gone[claim.id].append(d)
        elif quote_present(ce.quote, new) and ce.stance != "removed" and (claim.id, unit.id) not in rejudged:
            d.outcome, d.checked_at, d.resolved_at = "quote_intact", now, now
            d.grade_after = claim.grade.value
        else:
            d.outcome = "pending"
            attention.add(claim.id)
            recheck = True
        if d.outcome != "quote_intact":
            claim.source_changed = True
        db.add(d)
    db.flush()

    if gone:
        settle(db, source.project_id, {cid: ds for cid, ds in gone.items()})
        attention |= set(gone)
    if recheck:
        jobs.enqueue(db, "drift.check", {"project_id": source.project_id})
    return len(attention)


# --- re-checking with the Skeptic ----------------------------------------------------


def check_pending(db: Session, project_id: uuid.UUID) -> int:
    """The Skeptic re-reads claims whose quoted words changed, against the new text. Returns how many
    claims it settled; queues itself again if more are waiting."""
    from app.agents import skills
    from app.agents.evidence import sendable_labels
    from app.agents.skeptic import SkepticOut, _render, stance_of
    from app.llm import gateway

    pending = db.scalars(select(ClaimDrift).where(ClaimDrift.project_id == project_id,
                                                  ClaimDrift.outcome == "pending")
                         .order_by(ClaimDrift.detected_at)).all()
    by_claim: dict[uuid.UUID, list[ClaimDrift]] = defaultdict(list)
    for d in pending:
        by_claim[d.claim_id].append(d)
    if not by_claim:
        return 0
    batch = list(by_claim.items())[:CHECK_BATCH]
    names = {sid: name for sid, name in db.execute(
        select(Source.id, Source.name).where(Source.project_id == project_id)).all()}
    sendable = set(sendable_labels())
    model = llm.configured()
    skill = skills.load("skeptic") if model else None

    done = 0
    for claim_id, drifts in batch:
        claim = db.get(Claim, claim_id)
        now = datetime.now(UTC)
        if claim is None or claim.status == ClaimStatus.rejected:
            for d in drifts:
                d.outcome, d.checked_at, d.resolved_at = "unrelated", now, now
            db.commit()
            continue
        changed_ids = {d.evidence_id for d in drifts}
        cites = [ce for ce in claim.evidence if ce.stance != "removed" and not (ce.unit.meta or {}).get("removed_at")]
        readable = [ce for ce in cites if ce.unit.sensitivity in sendable]
        check = None
        if model and changed_ids <= {ce.evidence_id for ce in readable}:
            try:
                out = gateway.generate(db, SkepticOut, agent="skeptic", version=skill.version, tier=skill.tier,
                                       system=skill.instructions, prompt=_render(1, claim, readable, names),
                                       thinking=skill.thinking, attempts=3).value
                check = next((ch for ch in out.checks if ch.claim.strip().upper() == "C1"), None) or \
                    (out.checks[0] if out.checks else None)
            except gateway.AgentOutputInvalid:
                log.warning("drift: the Skeptic's answer for claim %s never matched the schema", claim_id)
        if check is None:
            # no model, a label no model may read, or no usable answer: a person decides
            for d in drifts:
                d.outcome, d.checked_at = "needs_person", now
        else:
            stances = {s.id.strip().upper(): stance_of(s.stance) for s in check.citations}
            for k, ce in enumerate(readable, start=1):
                if ce.evidence_id in changed_ids:
                    ce.stance = stances.get(f"C1-E{k}", "unrelated")
            stance = {ce.evidence_id: ce.stance for ce in readable}
            for d in drifts:
                d.outcome, d.checked_at = stance.get(d.evidence_id, "unrelated"), now
                d.note = check.note.strip()[:300]
            claim.skeptic = {**(claim.skeptic or {}), "overreach": check.overreach, "note": check.note.strip()[:300]}
        db.flush()
        settle(db, project_id, {claim_id: drifts})
        db.commit()
        done += 1

    if len(by_claim) > len(batch):
        jobs.enqueue(db, "drift.check", {"project_id": project_id},
                     run_after=datetime.now(UTC) + timedelta(seconds=5))
        db.commit()
    return done


# --- what it means for each claim ------------------------------------------------------


def settle(db: Session, project_id: uuid.UUID, drifts_by_claim: dict[uuid.UUID, list[ClaimDrift]]) -> None:
    """Regrades the affected claims and sends any whose support weakened back to review."""
    from app.agents.skeptic import regrade

    claims = {cid: db.get(Claim, cid) for cid in drifts_by_claim}
    for cid, drifts in drifts_by_claim.items():
        c = claims[cid]
        if c is not None and any(d.outcome in WEAKER for d in drifts):
            # marks the claim so code never removes it on its own: a person decides
            c.skeptic = {**(c.skeptic or {}), "drift": True}
    for run_id in {c.run_id for c in claims.values() if c is not None}:
        regrade(db, db.scalars(select(Claim).where(Claim.run_id == run_id)).all() if run_id
                else [c for c in claims.values() if c is not None and c.run_id is None])

    now = datetime.now(UTC)
    for cid, drifts in drifts_by_claim.items():
        c = claims[cid]
        if c is None:
            continue
        weaker = any(d.outcome in WEAKER for d in drifts)
        moved = any(d.grade_before and d.grade_before != c.grade.value for d in drifts)
        for d in drifts:
            d.grade_after = c.grade.value
        if not weaker and not moved:
            for d in drifts:  # re-checked and nothing changed: logged, no action needed
                d.resolved_at = now
            if not db.scalar(select(ClaimDrift.id).where(ClaimDrift.claim_id == cid, ClaimDrift.resolved_at.is_(None),
                                                         ClaimDrift.id.not_in([d.id for d in drifts])).limit(1)):
                c.source_changed = False
            continue
        reopened = c.status in APPROVED
        if reopened:
            what = "; ".join(sorted({OUTCOME_TEXT.get(d.outcome, d.outcome) for d in drifts}))
            db.add(ClaimVersion(claim_id=c.id, version=c.version, statement=c.statement, status=c.status,
                                grade=c.grade, note=f"Sent back for review: its source changed ({what})."))
            c.version += 1
            c.status = ClaimStatus.draft
            c.review_note = f"Back for review: its source changed ({what})."[:500]
            for d in drifts:
                d.reopened = True
        audit.record(db, actor_id=None, action="claim.drift", object_type="claim", object_id=c.id,
                     project_id=project_id, outcomes=sorted({d.outcome for d in drifts}),
                     grade=f"{drifts[0].grade_before}→{c.grade.value}", reopened=reopened)
    db.flush()


def resolve(db: Session, claim: Claim, user: User | None) -> None:
    """A person reviewed the claim after its source changed: the drift is dealt with."""
    if not claim.source_changed:
        return
    db.execute(update(ClaimDrift).where(ClaimDrift.claim_id == claim.id, ClaimDrift.resolved_at.is_(None))
               .values(resolved_at=datetime.now(UTC), resolved_by=user.id if user else None))
    claim.source_changed = False


# --- reading it back -------------------------------------------------------------------


def latest_by_claim(db: Session, claim_ids: list[uuid.UUID],
                    since: datetime | None = None) -> dict[uuid.UUID, ClaimDrift]:
    """The newest drift that mattered (not just a re-saved item) for each claim."""
    if not claim_ids:
        return {}
    q = select(ClaimDrift).where(ClaimDrift.claim_id.in_(claim_ids), ClaimDrift.outcome != "quote_intact")
    if since is not None:
        q = q.where(ClaimDrift.detected_at > since)
    out: dict[uuid.UUID, ClaimDrift] = {}
    for d in db.scalars(q.order_by(ClaimDrift.detected_at)):
        out[d.claim_id] = d
    return out


# --- demo mode: a change made by hand ----------------------------------------------------


def simulate(db: Session, unit: EvidenceUnit, text: str, user: User) -> int:
    """Demo mode only: rewrites an item as if someone had edited it in its tool, then runs exactly
    what a sync runs. The new words go through Sentinel like any synced text. The next real sync of
    the source puts the original back (and that, too, is checked as a change)."""
    from app import gatekeeper, lang
    from app.db.models import Redaction
    from app.sentinel import content_hash, scan, strictest

    old = f"{unit.title}\n{unit.text}"
    body = scan(text[:20_000], floor=unit.sensitivity)
    previous = unit.sensitivity
    db.query(Redaction).filter(Redaction.evidence_id == unit.id).delete()
    unit.text = body.text
    unit.content_hash = content_hash(unit.title + "\n" + body.text)
    unit.sensitivity = strictest(unit.sensitivity, body.sensitivity)  # an edit never lowers the label
    unit.language = lang.detect(body.text)
    unit.embedding = None
    unit.meta = {**(unit.meta or {}), "simulated_at": datetime.now(UTC).isoformat()}
    db.flush()
    for finding, start, end in body.placeholders:
        db.add(Redaction(evidence_id=unit.id, rule_id=finding.rule_id, category=finding.category,
                         start=start, end=end))
    source = db.get(Source, unit.source_id)
    affected = detect(db, source, [(unit, old, False)], [], simulated=True)
    audit.record(db, actor_id=user.id, action="evidence.simulate_change", object_type="evidence",
                 object_id=unit.id, project_id=unit.project_id, claims=affected)
    jobs.enqueue(db, "project.embed", {"project_id": unit.project_id})
    db.commit()
    gatekeeper.relabel_evidence(db, unit, previous)
    return affected
