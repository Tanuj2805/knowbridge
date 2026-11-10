"""Gap Interviewer (agent 8): asks the person leaving about what the evidence
leaves unclear, and folds the answers back into the ledger.

  1. `prepare`: code picks the gaps (sources that disagree, questions nobody
     answered, claims the Skeptic doubts, big risks with no owner, key decisions
     with no reason), weighting anything tied to the leaver; the model only
     phrases them as questions.
  2. The leaver answers in the app, one question at a time. Each answer is
     masked by Sentinel and stored as evidence ("Gap Interview: <name>").
  3. `apply_answer`: the model reads what the answer says (confirms, corrects,
     picks a side, adds an owner or date); code applies it and re-grades, so a
     confirmed claim becomes Verified or Attested and a settled conflict is resolved.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, gatekeeper, guard, lang
from app.agents import skills
from app.agents.base import context_for, step
from app.agents.evidence import local_date, sendable_labels
from app.agents.facts import SYSTEM_DATA
from app.agents.skeptic import INTERVIEW_KIND, regrade
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    EvidenceUnit,
    GapQuestion,
    Grade,
    Handover,
    HandoverStatus,
    QuestionStatus,
    Redaction,
    Run,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    User,
)
from app.llm import LLMUnavailable, gateway
from app.sentinel import content_hash, scan, strictest

log = logging.getLogger(__name__)
MAX_QUESTIONS = 12
OWNERLESS = {ClaimType.risk, ClaimType.blocker, ClaimType.next_action}


# --- choosing the gaps (code) -------------------------------------------------


@dataclass
class Gap:
    kind: str  # "choose" (two claims disagree), "confirm" (doubted), "fill" (something missing)
    claims: list[Claim]
    reason: str
    priority: float


def latest_run(db: Session, project_id: uuid.UUID) -> Run | None:
    return db.scalars(select(Run).where(Run.project_id == project_id, Run.kind == "reconstruct",
                                        Run.status == RunStatus.done).order_by(Run.created_at.desc())).first()


def find_gaps(db: Session, run: Run, leaver: User, principal) -> list[Gap]:
    """The run's weakest spots that the leaver can see, most important first."""
    claims = db.scalars(select(Claim).where(Claim.run_id == run.id, Claim.status != ClaimStatus.rejected)).all()
    ids = {c.id for c in claims}
    current = [c for c in claims if c.superseded_by not in ids]
    # Only what the leaver may see, and only labels the model may read (it phrases the questions).
    visible = gatekeeper.visible_evidence_ids(db, principal, run.project_id,
                                              [ce.evidence_id for c in current for ce in c.evidence])
    sendable = set(sendable_labels())
    current = [c for c in current if c.evidence and c.sensitivity in sendable
               and all(ce.evidence_id in visible for ce in c.evidence)]
    by_id = {c.id: c for c in current}
    first_name = leaver.name.split()[0].lower() if leaver.name else ""

    gaps: list[Gap] = []
    paired: set[frozenset] = set()
    for c in current:
        weight = c.impact * 10 + (15 if first_name and first_name in c.statement.lower() else 0)
        partners = [by_id[o] for o in (c.conflicts_with or []) if o in by_id]
        if partners:
            for other in partners:
                if frozenset((c.id, other.id)) not in paired:
                    paired.add(frozenset((c.id, other.id)))
                    gaps.append(Gap("choose", [c, other], "Two sources disagree.", weight + 30))
        elif c.grade == Grade.missing:
            gaps.append(Gap("fill", [c], "Asked in the evidence, but nobody answered.", weight + 25))
        elif c.grade == Grade.conflicting:
            gaps.append(Gap("confirm", [c], c.grade_reason, weight + 20))
        elif c.type in OWNERLESS and not c.owner_name and c.impact >= 3:
            gaps.append(Gap("fill", [c], "Nobody is named to handle this.", weight + 15))
        elif c.grade == Grade.inferred and c.impact >= 2 and not c.grade_reason.startswith(SYSTEM_DATA):
            gaps.append(Gap("confirm", [c], c.grade_reason or "Only implied by the evidence.", weight + 10))
        elif c.type == ClaimType.decision and not c.rationale and c.impact >= 3:
            gaps.append(Gap("fill", [c], "No reason is recorded for this decision.", weight + 8))
    gaps.sort(key=lambda g: -g.priority)
    return gaps[:MAX_QUESTIONS]


# --- phrasing them (model) ----------------------------------------------------


class Asked(BaseModel):
    gap: str = Field(description="gap id, e.g. G3")
    question: str
    why: str = Field(default="", description="one sentence: why it matters for the person taking over")


class AskedOut(BaseModel):
    questions: list[Asked]


def _where(c: Claim, source_names: dict) -> str:
    ce = min(c.evidence, key=lambda e: e.unit.occurred_at or datetime.max.replace(tzinfo=UTC))
    u = ce.unit
    return ", ".join(x for x in (source_names.get(u.source_id, ""),
                                 local_date(u.occurred_at).isoformat() if u.occurred_at else "") if x)


def _gap_text(n: int, g: Gap, source_names: dict) -> str:
    lines = [f"G{n} | {g.kind} | {g.reason}"]
    tags = ["a", "b"] if g.kind == "choose" else ["claim"]
    for tag, c in zip(tags, g.claims, strict=False):
        lines.append(f'  {tag}: "{c.statement}" ({_where(c, source_names)})')
        if c.owner_name:
            lines.append(f"     owner: {c.owner_name}")
    return "\n".join(lines)


def _fallback(g: Gap) -> tuple[str, str]:
    """Plain questions for when the model can't be reached."""
    a = g.claims[0].statement.rstrip(".")
    if g.kind == "choose":
        return f"Which is right now: “{a}” or “{g.claims[1].statement.rstrip('.')}”?", g.reason
    if g.kind == "confirm":
        return f"Is this right: “{a}”? If not, what is true?", g.reason
    if g.claims[0].type == ClaimType.open_question:
        return (a if a.endswith("?") else f"{a}?"), g.reason
    if g.claims[0].type in OWNERLESS:
        return f"Who will handle this after you leave: “{a}”?", g.reason
    return f"Why was this decided: “{a}”?", g.reason


def prepare(db: Session, handover_id: uuid.UUID) -> int:
    """Writes the interview questions for a handover. Returns how many (0 if already written)."""
    h = db.get(Handover, handover_id)
    if h is None or db.scalar(select(func.count()).select_from(GapQuestion).where(GapQuestion.handover_id == h.id)):
        return 0
    run = latest_run(db, h.project_id)
    if run is None:
        return 0
    leaver = db.get(User, h.leaver_id)
    principal = gatekeeper.principal(db, h.project_id, h.leaver_id)
    ctx = context_for(db, run, principal)
    skill = skills.load("gap_interviewer")
    with step(db, ctx, "interviewer") as row:
        gaps = find_gaps(db, run, leaver, principal)
        row.items_in = len(gaps)
        written: dict[str, Asked] = {}
        if gaps:
            prompt = (f"Person answering: {leaver.name} (leaving the project).\n\n"
                      + "\n\n".join(_gap_text(n, g, ctx.source_names) for n, g in enumerate(gaps, start=1)))
            try:
                out = gateway.generate(db, AskedOut, agent="gap_interviewer", version=skill.version, tier=skill.tier,
                                       system=skill.instructions, prompt=prompt, thinking=skill.thinking,
                                       budget=ctx.budget, usage=ctx.usage_for("interviewer")).value
                written = {a.gap.strip().upper(): a for a in out.questions if a.question.strip()}
            except (gateway.AgentOutputInvalid, LLMUnavailable) as e:
                log.warning("gap interviewer: using plain questions (%s)", e)
        for n, g in enumerate(gaps, start=1):
            asked = written.get(f"G{n}")
            question, why = (asked.question.strip(), asked.why.strip()) if asked else _fallback(g)
            db.add(GapQuestion(
                handover_id=h.id, claim_id=g.claims[0].id, question=question[:1000], why_asked=why[:500],
                priority=int(g.priority), assignee_id=h.leaver_id, position=n,
                meta={"kind": g.kind, "reason": g.reason, "claims": [str(c.id) for c in g.claims]},
            ))
        kinds = {k: sum(1 for g in gaps if g.kind == k) for k in ("choose", "confirm", "fill")}
        row.items_out = len(gaps)
        row.summary = (f"Wrote {len(gaps)} questions for {leaver.name}: {kinds['choose']} where sources disagree, "
                       f"{kinds['confirm']} to confirm, {kinds['fill']} to fill in.")
    h.status = HandoverStatus.interviewing
    db.commit()
    return len(gaps)


# --- answers become evidence ---------------------------------------------------


def interview_source(db: Session, h: Handover) -> Source:
    """One source per handover holds its answers, readable by everyone on the project."""
    for s in db.scalars(select(Source).where(Source.project_id == h.project_id, Source.kind == SourceKind.interview)):
        if (s.config or {}).get("handover_id") == str(h.id):
            return s
    leaver = db.get(User, h.leaver_id)
    s = Source(project_id=h.project_id, kind=SourceKind.interview, name=f"Gap Interview: {leaver.name}",
               status=SourceStatus.ready, config={"handover_id": str(h.id)}, created_by=h.created_by)
    db.add(s)
    db.flush()
    gatekeeper.sync_source(db, s)
    return s


def record_answer(db: Session, q: GapQuestion, answer: str, by: User) -> EvidenceUnit:
    """Stores an answer as evidence, masked by Sentinel like everything else."""
    h = db.get(Handover, q.handover_id)
    source = interview_source(db, h)
    body, title = scan(answer.strip()[:4000], floor=source.default_sensitivity), scan(q.question[:500])
    unit = EvidenceUnit(
        project_id=h.project_id, source_id=source.id, external_id=f"gap:{q.id}", kind=INTERVIEW_KIND,
        title=title.text, text=body.text, author=by.name, occurred_at=datetime.now(UTC),
        locator=f"Gap Interview · question {q.position}", content_hash=content_hash(title.text + "\n" + body.text),
        sensitivity=strictest(body.sensitivity, title.sensitivity), language=lang.detect(body.text),
        meta={"question_id": str(q.id), "handover_id": str(h.id)}
        | ({"label_reasons": body.sensitivity_reasons[:5]} if body.sensitivity_reasons else {}),
    )
    db.add(unit)
    db.flush()
    for finding, start, end in body.placeholders:
        db.add(Redaction(evidence_id=unit.id, rule_id=finding.rule_id, category=finding.category,
                         start=start, end=end))
    source.item_count = (source.item_count or 0) + 1
    source.last_synced_at = datetime.now(UTC)
    gatekeeper.sync_evidence(db, [unit])
    q.answer_evidence_id = unit.id
    return unit


# --- reading an answer (model) and applying it (code) -------------------------


class Reading(BaseModel):
    verdict: str = Field(description='"confirms", "corrects", "picks_a", "picks_b", "both", "adds" or "unknown"')
    statement: str = Field(default="", description=(
        'REQUIRED for "corrects": what is true now, one self-contained sentence naming the ticket or system '
        '(e.g. "KCT-96 is resolved; the fix is waiting to be merged."). Also for "adds". Otherwise empty.'))
    owner: str = Field(default="", description="person responsible, only if the answer names one")
    due: str = Field(default="", description="deadline as YYYY-MM-DD, only if the answer gives one")
    reason: str = Field(default="", description="the reason, only if the answer gives one")
    follow_ups: list[str] = Field(default_factory=list, description="tasks the answer commits someone to")


VERDICTS = ("confirms", "corrects", "picks_a", "picks_b", "both", "adds", "unknown")


def verdict_of(text: str) -> str:
    t = text.strip().lower().replace(" ", "_")
    return next((v for v in VERDICTS if t.startswith(v[:6]) and (not v.startswith("picks") or t.startswith(v))),
                "unknown")


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s.strip()[:10]) if s.strip() else None
    except ValueError:
        return None


def _reading_prompt(q: GapQuestion, claims: list[Claim], unit: EvidenceUnit) -> str:
    tags = ["a", "b"] if (q.meta or {}).get("kind") == "choose" else ["claim"]
    lines = [f"Question: {q.question}", f"Kind of gap: {(q.meta or {}).get('kind', 'confirm')}"]
    lines += [f'Claim {tag}: "{c.statement}"' for tag, c in zip(tags, claims, strict=False)]
    lines.append(f"<evidence id=\"answer\" author=\"{escape(unit.author, quote=True)}\">\n"
                 f"{guard.fence(unit.text)}\n</evidence>")
    return "\n".join(lines)


def apply_answer(db: Session, question_id: uuid.UUID) -> dict:
    """Reads an answered question and updates the ledger. Returns what changed."""
    q = db.get(GapQuestion, question_id)
    meta = dict(q.meta or {}) if q else {}
    if q is None or q.status != QuestionStatus.answered or meta.get("applied") or not q.answer_evidence_id:
        return {}
    unit = db.get(EvidenceUnit, q.answer_evidence_id)
    claims = [c for c in (db.get(Claim, uuid.UUID(cid)) for cid in meta.get("claims", [])) if c is not None]
    if not claims:
        return {}
    skill = skills.load("gap_reader")
    reading = gateway.generate(db, Reading, agent="gap_reader", version=skill.version, tier=skill.tier,
                               system=skill.instructions, prompt=_reading_prompt(q, claims, unit),
                               thinking=skill.thinking).value
    verdict = verdict_of(reading.verdict)
    quote = unit.text[:500]
    effects: list[str] = []

    def cite(c: Claim, stance: str) -> None:
        if not any(ce.evidence_id == unit.id for ce in c.evidence):
            c.evidence.append(ClaimEvidence(evidence_id=unit.id, quote=quote, quote_hash=content_hash(quote),
                                            stance=stance))

    def new_claim(ctype: ClaimType, statement: str, like: Claim) -> Claim:
        c = Claim(project_id=like.project_id, run_id=like.run_id, type=ctype, statement=statement.strip()[:1000],
                  subject=like.subject, owner_name=reading.owner.strip()[:200], due_date=_date(reading.due),
                  valid_from=datetime.now(UTC), impact=like.impact, created_by_agent="gap_interviewer",
                  sensitivity=unit.sensitivity, skeptic={"from_interview": True})
        db.add(c)
        db.flush()
        cite(c, "supports")
        return c

    target = claims[0]
    if verdict in ("picks_a", "picks_b") and len(claims) == 2:
        keep, drop = (claims[0], claims[1]) if verdict == "picks_a" else (claims[1], claims[0])
        cite(keep, "supports")
        cite(drop, "contradicts")
        drop.status = ClaimStatus.rejected
        drop.grade_reason = f"Corrected by {unit.author} in the Gap Interview."
        keep.conflicts_with = [x for x in (keep.conflicts_with or []) if x != drop.id]
        drop.conflicts_with = [x for x in (drop.conflicts_with or []) if x != keep.id]
        # History follows the claim that stays: "webhooks → polling every 60 s" becomes "→ every 30 s".
        for earlier in db.scalars(select(Claim).where(Claim.superseded_by == drop.id)):
            earlier.superseded_by = keep.id
        effects.append(f"kept “{keep.statement[:80]}”, set aside “{drop.statement[:80]}”")
    elif verdict == "both" and len(claims) == 2:
        a, b = claims
        for c in claims:
            cite(c, "supports")
        a.conflicts_with = [x for x in (a.conflicts_with or []) if x != b.id]
        b.conflicts_with = [x for x in (b.conflicts_with or []) if x != a.id]
        effects.append("both are true: no longer a conflict")
    elif verdict == "confirms":
        for c in claims:
            cite(c, "supports")
        effects.append("confirmed")
    elif verdict == "corrects":
        # The true state replaces the claim. If the model didn't spell it out, the leaver's own
        # words are the correction ("KCT-96 SQL accuracy bug: its resolved but not merged yet").
        topic = (target.subject or "Update").strip()
        own_words = f"{topic[:1].upper()}{topic[1:]}: {unit.text.strip()[:300]} ({unit.author}, Gap Interview)"
        statement = reading.statement.strip() or own_words
        fixed = new_claim(target.type, statement, target)
        for c in claims:
            cite(c, "contradicts")
            c.superseded_by, c.valid_to = fixed.id, datetime.now(UTC)
        effects.append(f"corrected to “{fixed.statement[:100]}”")
    elif verdict == "adds":
        cite(target, "supports")
        if reading.owner.strip() and not target.owner_name:
            target.owner_name = reading.owner.strip()[:200]
            effects.append(f"owner: {target.owner_name}")
        if _date(reading.due):
            target.due_date = _date(reading.due)
            effects.append(f"due {target.due_date.isoformat()}")
        if reading.reason.strip() and not target.rationale:
            target.rationale = reading.reason.strip()[:2000]
            effects.append("reason added")
        if reading.statement.strip() and target.type != ClaimType.open_question:
            new_claim(target.type, reading.statement, target)
            effects.append(f"new: “{reading.statement.strip()[:100]}”")
        effects = effects or ["answer added as evidence"]
    else:
        effects.append("no change (the answer didn't settle it)")
    for task in reading.follow_ups[:3]:
        if task.strip():
            new_claim(ClaimType.next_action, task, target)
            effects.append(f"next action: “{task.strip()[:100]}”")

    db.flush()
    regrade(db, db.scalars(select(Claim).where(Claim.run_id == target.run_id)).all())
    q.meta = meta | {"applied": {"verdict": verdict, "effects": effects}}
    audit.record(db, actor_id=None, action="interview.applied", object_type="gap_question", object_id=q.id,
                 project_id=target.project_id, verdict=verdict)
    db.commit()
    return q.meta["applied"]
