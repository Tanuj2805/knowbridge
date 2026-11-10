"""Composer (agent 9): writes the Handover Pack and the 30-day plan for one
person, from approved claims only.

Code decides what goes in and where: the latest run's approved (or edited)
claims, their current versions, filtered to what the person taking over may
see; anything held back becomes a "withheld" note on its section. The model
only writes the brief, one intro per section and the 30-day plan, and never
sees a confidential claim.

Each composition is a new version. The approver previews it and publishes;
the person taking over only ever sees the published version.
"""

import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, gatekeeper
from app.agents import skills
from app.agents.base import context_for, step
from app.agents.evidence import local_date, sendable_labels
from app.agents.interviewer import latest_run
from app.connectors.base import RetryLater
from app.db.models import (
    Claim,
    ClaimStatus,
    ClaimType,
    Grade,
    Handover,
    HandoverSection,
    PlanItem,
    Project,
    Source,
    User,
)
from app.llm import LLMUnavailable, gateway

log = logging.getLogger(__name__)
APPROVED = (ClaimStatus.approved, ClaimStatus.edited)
_REF = re.compile(r"\bC\d+\b")
_REF_TEXT = re.compile(r"\s*\((?:C\d+(?:\s*(?:,|and)\s*)?)+\)|\bC\d+\b,?\s*")
GRADE_ORDER = {g: i for i, g in enumerate([Grade.verified, Grade.attested, Grade.supported, Grade.inferred,
                                           Grade.conflicting, Grade.missing])}

# (key, title, what belongs there). "yours" and "open" are decided per claim below.
SECTIONS: list[tuple[str, str]] = [
    ("brief", "The project in brief"),
    ("yours", "What you're taking over"),
    ("decisions", "Key decisions and why"),
    ("people", "Who owns what"),
    ("systems", "Systems and dependencies"),
    ("risks", "Risks and blockers"),
    ("open", "Open questions"),
    ("plan", "Your first 30 days"),
]
TITLES = dict(SECTIONS)
# Claims per section the model reads (a 352-claim project timed out at 57,000 characters).
# The plan comes mostly from risks, so they get more room.
PROMPT_CAP = {"risks": 30, "open": 15}


def section_of(c: Claim, leaver_first: str) -> str:
    if c.grade in (Grade.conflicting, Grade.missing) or c.type == ClaimType.open_question:
        return "open"
    if c.type == ClaimType.owner:
        mentions_leaver = leaver_first and leaver_first in f"{c.owner_name} {c.statement}".lower()
        return "yours" if mentions_leaver else "people"
    return {
        ClaimType.decision: "decisions",
        ClaimType.contact: "people",
        ClaimType.dependency: "systems",
        ClaimType.risk: "risks",
        ClaimType.blocker: "risks",
        ClaimType.recurring_problem: "risks",
        ClaimType.next_action: "risks",
    }.get(c.type, "risks")


# --- what the model writes ------------------------------------------------------


class Intro(BaseModel):
    section: str = Field(description="section key, e.g. decisions")
    text: str


class Task(BaseModel):
    week: int = Field(description="1 to 4")
    title: str
    detail: str = ""
    owner: str = ""
    due: str = Field(default="", description="YYYY-MM-DD, only if a claim gives a date")
    claims: list[str] = Field(default_factory=list, description="ids of the claims it comes from, e.g. ['C3']")


class Composition(BaseModel):
    brief: str
    intros: list[Intro] = Field(default_factory=list)
    plan: list[Task] = Field(default_factory=list)


# --- composing ------------------------------------------------------------------


@dataclass
class Picked:
    by_section: dict[str, list[Claim]] = field(default_factory=dict)
    withheld: dict[str, list[Claim]] = field(default_factory=dict)
    history: dict[uuid.UUID, list[Claim]] = field(default_factory=dict)  # current claim -> what it replaced


def pick(db: Session, h: Handover) -> Picked:
    """The approved, current claims, split into what the person taking over may see and what is withheld."""
    run = latest_run(db, h.project_id)
    out = Picked()
    if run is None:
        return out
    claims = db.scalars(select(Claim).where(Claim.run_id == run.id)).all()
    ids = {c.id for c in claims}
    current = [c for c in claims if c.status in APPROVED and c.superseded_by not in ids]
    successor = gatekeeper.principal(db, h.project_id, h.successor_id)
    visible = gatekeeper.visible_evidence_ids(db, successor, h.project_id,
                                              [ce.evidence_id for c in current for ce in c.evidence])
    leaver = db.get(User, h.leaver_id)
    first = (leaver.name.split()[0] if leaver and leaver.name else "").lower()
    for c in current:
        target = out.by_section if c.evidence and all(ce.evidence_id in visible for ce in c.evidence) \
            else out.withheld
        target.setdefault(section_of(c, first), []).append(c)
    for c in claims:
        if c.superseded_by in ids and c.status != ClaimStatus.rejected:
            out.history.setdefault(c.superseded_by, []).append(c)
    for group in out.by_section.values():
        group.sort(key=lambda c: (-c.impact, GRADE_ORDER.get(c.grade, 9), c.valid_from or datetime.min.replace(
            tzinfo=UTC)))
    return out


def _block(c: Claim, history: list[Claim], source_names: dict) -> dict:
    """A claim as it appears in the pack: a snapshot, so a published pack never changes under the reader."""
    return {
        "claim_id": str(c.id), "type": c.type.value, "statement": c.statement, "rationale": c.rationale,
        "grade": c.grade.value, "grade_reason": c.grade_reason, "owner": c.owner_name,
        "due": c.due_date.isoformat() if c.due_date else None,
        "since": local_date(c.valid_from).isoformat() if c.valid_from else None,
        "history": [{"statement": o.statement, "until": local_date(o.valid_to).isoformat() if o.valid_to else None}
                    for o in history],
        "cites": [{"evidence_id": str(ce.evidence_id), "quote": ce.quote, "kind": ce.unit.kind,
                   "source": source_names.get(ce.unit.source_id, ""), "author": ce.unit.author,
                   "date": local_date(ce.unit.occurred_at).isoformat() if ce.unit.occurred_at else None,
                   "permalink": ce.unit.permalink} for ce in c.evidence],
    }


def _prompt(h: Handover, picked: Picked, refs: dict[str, Claim], names: dict[uuid.UUID, str], today: date) -> str:
    lines = [f"Leaving: {names[h.leaver_id]}" + (f" (last day {h.leaver_last_day.isoformat()})" if h.leaver_last_day
                                                 else ""),
             f"Taking over: {names[h.successor_id]}", f"Pack written on: {today.isoformat()}", ""]
    by_claim = {c.id: ref for ref, c in refs.items()}
    for key, title in SECTIONS:
        group = [c for c in picked.by_section.get(key, []) if c.id in by_claim]
        if not group:
            continue
        lines.append(f"## {key}: {title}")
        for c in group:
            extra = "".join(x for x in (f" | owner: {c.owner_name}" if c.owner_name else "",
                                        f" | due: {c.due_date.isoformat()}" if c.due_date else ""))
            lines.append(f"{by_claim[c.id]} | {c.type.value} | {c.grade.value} | {c.statement}{extra}")
        lines.append("")
    return "\n".join(lines)


def _fallback_plan(picked: Picked, today: date) -> list[Task]:
    """Without the model: deadlines first, then high-impact risks."""
    tasks = []
    for c in picked.by_section.get("risks", []) + picked.by_section.get("open", []):
        if c.due_date or c.impact >= 3:
            days = (c.due_date - today).days if c.due_date else 7
            tasks.append(Task(week=min(4, max(1, math.ceil(max(days, 1) / 7))), title=c.statement[:120],
                              owner=c.owner_name, due=c.due_date.isoformat() if c.due_date else "",
                              claims=[str(c.id)]))
    return sorted(tasks, key=lambda t: (t.week, t.due or "9999"))[:12]


def compose(db: Session, handover_id: uuid.UUID) -> int:
    """Writes a new version of the pack and plan. Returns the version number (0 if nothing to write)."""
    h = db.get(Handover, handover_id)
    run = latest_run(db, h.project_id) if h else None
    if h is None or run is None:
        return 0
    picked = pick(db, h)
    if not picked.by_section and not picked.withheld:
        return 0
    project = db.get(Project, h.project_id)
    names = {u.id: u.name for u in db.scalars(select(User).where(
        User.id.in_([h.leaver_id, h.successor_id, h.approver_id])))}
    source_names = {sid: n for sid, n in db.execute(select(Source.id, Source.name)
                                                    .where(Source.project_id == h.project_id))}
    today = local_date(datetime.now(UTC))
    version = (db.scalar(select(func.max(HandoverSection.version)).where(HandoverSection.handover_id == h.id))
               or 0) + 1
    ctx = context_for(db, run, gatekeeper.principal(db, h.project_id, h.approver_id))
    skill = skills.load("composer")
    sendable = set(sendable_labels())

    with step(db, ctx, "composer") as row:
        # The model only needs the most important claims to write intros and a plan; every approved
        # claim still goes into the pack. Sections are already sorted: high impact, best grade first.
        def for_model(key: str) -> list[Claim]:
            return [c for c in picked.by_section.get(key, []) if c.sensitivity in sendable][:PROMPT_CAP.get(key, 20)]

        refs = {f"C{n}": c for n, c in enumerate((c for key, _ in SECTIONS for c in for_model(key)), start=1)}
        row.items_in = sum(len(g) for g in picked.by_section.values())
        try:
            written = gateway.generate(
                db, Composition, agent="composer", version=skill.version, tier=skill.tier,
                system=skill.instructions, prompt=_prompt(h, picked, refs, names, today), thinking=skill.thinking,
                budget=ctx.budget, usage=ctx.usage_for("composer"), attempts=2,
            ).value
            without_model = ""
        except (gateway.AgentOutputInvalid, LLMUnavailable, RetryLater) as e:
            # The pack doesn't need the model: every claim, section and withheld note comes from code.
            # Only the summaries and the plan's wording do, so write it now rather than wait.
            log.warning("composer: writing the pack without the model (%s)", e)
            written = Composition(brief=project.description or "", plan=_fallback_plan(picked, today))
            without_model = " The model didn't answer, so the brief, intros and plan were written without it; " \
                            "write a new version later to add them."
        intros = {i.section.strip().lower(): i.text.strip() for i in written.intros}

        approver = names.get(h.approver_id, "the approver")
        for position, (key, title) in enumerate(SECTIONS):
            blocks = [_block(c, picked.history.get(c.id, []), source_names) for c in picked.by_section.get(key, [])]
            held = picked.withheld.get(key, [])
            # Why each was held back: its label, or "source access" for a team item from a source they can't open.
            reasons = sorted({c.sensitivity.value if c.sensitivity.value != "team" else "source access" for c in held})
            withheld = {"count": len(held), "labels": reasons, "ask": approver} if held else {}
            if key == "brief":
                content = {"intro": written.brief.strip() or (project.description or ""), "blocks": []}
            elif key == "plan":
                content = {"intro": intros.get("plan", ""), "blocks": []}
            elif not blocks and not held:
                continue
            else:
                content = {"intro": intros.get(key, ""), "blocks": blocks}
            db.add(HandoverSection(handover_id=h.id, recipient_id=h.successor_id, version=version, key=key,
                                   position=position, title=title, content=content, withheld=withheld))

        def claim_ids(task: Task) -> list[uuid.UUID]:
            out = []
            # Models sometimes put the ids in the text ("…the only Firebase Owner (C65)") instead of the list.
            for ref in [*task.claims, *_REF.findall(f"{task.title} {task.detail}")]:
                ref = ref.strip().upper()
                if ref in refs:
                    out.append(refs[ref].id)
                else:
                    try:
                        out.append(uuid.UUID(ref.lower()))  # the fallback plan uses claim ids directly
                    except ValueError:
                        continue
            return out

        def clean(text: str) -> str:
            """Without claim ids: "…the only Firebase Owner (C65)." → "…the only Firebase Owner."."""
            text = re.sub(r"\s+([.,;:])", r"\1", _REF_TEXT.sub(" ", text))
            return re.sub(r"\s{2,}", " ", text).strip(" ,;")

        # Each task once: models sometimes write a task twice, once empty and once with its detail.
        tasks: dict[str, Task] = {}
        for task in written.plan:
            key = " ".join(task.title.lower().split())
            if key and (key not in tasks or len(task.detail) > len(tasks[key].detail)):
                merged = task.model_copy(update={"claims": [*tasks[key].claims, *task.claims]}) if key in tasks \
                    else task
                tasks[key] = merged
        planned = 0
        for task in list(tasks.values())[:12]:
            ids = list(dict.fromkeys(claim_ids(task)))
            if not task.title.strip() or not ids:
                continue  # every task has to come from a claim
            task = task.model_copy(update={"title": clean(task.title), "detail": clean(task.detail)})
            try:
                due = date.fromisoformat(task.due.strip()[:10]) if task.due.strip() else None
            except ValueError:
                due = None
            db.add(PlanItem(handover_id=h.id, recipient_id=h.successor_id, version=version,
                            week=min(4, max(1, task.week)), title=task.title.strip()[:300],
                            detail=task.detail.strip()[:2000], owner_name=task.owner.strip()[:200], due_date=due,
                            claim_ids=ids))
            planned += 1
        withheld_total = sum(len(g) for g in picked.withheld.values())
        row.items_out = planned
        row.summary = (f"Wrote version {version} of the pack for {names.get(h.successor_id)}: "
                       f"{row.items_in} claims in {sum(1 for g in picked.by_section.values() if g)} sections, "
                       f"{planned} plan tasks" + (f", {withheld_total} withheld" if withheld_total else "") + "."
                       + without_model)
    audit.record(db, actor_id=None, action="pack.composed", object_type="handover", object_id=h.id,
                 project_id=h.project_id, version=version)
    db.commit()
    return version
