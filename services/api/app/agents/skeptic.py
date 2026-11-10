"""Skeptic (agent 7): checks every claim against the passages it cites, and
nothing else, then grades it.

The model only judges each passage (supports / partial / contradicts /
unrelated) and whether the claim says more than its passages, or gives a reason
they don't state. The grade itself is computed by `decide` from those
judgements, so grades are reproducible and can be recomputed at any time
(`regrade`), for example after a Gap Interview answer.
"""

import hashlib
import re
from dataclasses import dataclass
from html import escape

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import guard
from app.agents import skills
from app.agents.base import AgentContext, generate_many, is_done, mark_done, step, tracked
from app.agents.evidence import local_date, sendable_labels
from app.agents.facts import SYSTEM_DATA, person
from app.db.models import Claim, ClaimEvidence, ClaimStatus, ClaimType, EvidenceUnit, Grade

BATCH = 8  # claims per call
PASSAGE_CHARS = 1_200
STANCES = {"supports", "partial", "contradicts", "unrelated"}
REMOVED = "Removed by the Skeptic"
INTERVIEW_KIND = "interview_answer"  # evidence kind of a Gap Interview answer


class Stance(BaseModel):
    id: str = Field(description="passage id, e.g. C2-E1")
    stance: str = Field(description='"supports", "partial", "contradicts" or "unrelated"')


class Check(BaseModel):
    claim: str = Field(description="claim id, e.g. C2")
    citations: list[Stance]
    overreach: bool = Field(default=False, description="the claim states something none of its passages say")
    reason_supported: bool = Field(default=True, description="false if it gives a reason no passage states")
    note: str = Field(default="", description="one short sentence on what is missing or wrong; empty if fine")


class SkepticOut(BaseModel):
    checks: list[Check]


# --- the grading rules (code, not model) -------------------------------------


@dataclass(frozen=True)
class Cite:
    stance: str
    source: str  # source id
    author: str
    attested: bool = False  # a Gap Interview answer from the person leaving


def decide(*, ctype: ClaimType, cites: list[Cite], overreach: bool, unanswered: bool, conflicting: bool,
           system: str = "", note: str = "") -> tuple[Grade | None, str]:
    """The grade and a reason a person can read. None means the claim has no support and is removed."""
    if system:
        return Grade.verified, f"Read straight from {system}, not written by a model."
    supports = [c for c in cites if c.stance == "supports"]
    documents = [c for c in supports if not c.attested]
    confirmed = [c for c in supports if c.attested]
    partial = [c for c in cites if c.stance == "partial"]
    contradicts = [c for c in cites if c.stance == "contradicts"]
    if not supports and not partial and not contradicts:
        return None, f"{REMOVED}: none of its passages are about it.{f' {note}' if note else ''}"
    if any(c.attested for c in contradicts):
        return Grade.conflicting, note or "The person leaving says otherwise in the Gap Interview."
    # The person leaving settles a doubt: their confirmation outranks a passage that only seemed to disagree.
    if documents and confirmed:
        return Grade.verified, "Stated in the evidence and confirmed by the person leaving."
    if confirmed:
        return Grade.attested, "Confirmed by the person leaving, in the Gap Interview."
    if not supports and not partial:
        return Grade.conflicting, note or "Its own passage seems to say otherwise; a person needs to check."
    if conflicting or contradicts:
        return Grade.conflicting, "Sources disagree; a person needs to decide which is right."
    if ctype == ClaimType.open_question and unanswered:
        return Grade.missing, "Asked in the evidence, but nobody answered."
    if overreach or not supports:
        return Grade.inferred, note or ("Says more than its passages do." if overreach
                                        else "Its passages back only part of it.")
    independent = {(c.source, c.author.strip().lower()) for c in supports}
    if len(independent) >= 2:
        return Grade.verified, f"{len(independent)} separate sources or people say this."
    return Grade.supported, "Stated in one place."


def stance_of(text: str) -> str:
    """A stance read leniently ("Supports.", "partially supports", "contradicts it")."""
    t = text.strip().lower()
    if t.startswith("support"):
        return "supports"
    for word in ("partial", "contradict"):
        if t.startswith(word):
            return "partial" if word == "partial" else "contradicts"
    return "unrelated"


def _owner_by_work(c: Claim, ce: ClaimEvidence) -> bool:
    """The cited work was written by, or assigned to, the claim's named owner."""
    if c.type != ClaimType.owner or not c.owner_name:
        return False
    u = ce.unit
    return any(who and person(who, [c.owner_name]) == c.owner_name
               for who in [u.author, *((u.meta or {}).get("assignees") or [])])


def _stance(c: Claim, ce: ClaimEvidence) -> str:
    """The Skeptic's stance, except that work written by or assigned to the named owner
    supports an ownership claim: that is what ownership means here, so code decides it."""
    if ce.stance == "partial" and _owner_by_work(c, ce):
        return "supports"
    return ce.stance


def _inputs(c: Claim) -> dict | None:
    """What `decide` needs for this claim, or None if the Skeptic hasn't checked it yet."""
    verdict = c.skeptic or {}
    system = c.grade_reason.split(": ", 1)[1] if c.grade_reason.startswith(f"{SYSTEM_DATA}: ") else ""
    if not verdict and not system:
        return None
    # For ownership, the work itself is the evidence: "overreach" there mostly means "the word owns isn't used".
    by_work = any(_owner_by_work(c, ce) and ce.stance in ("supports", "partial") for ce in c.evidence)
    return {
        "ctype": c.type, "system": system, "note": "" if by_work else verdict.get("note", ""),
        "overreach": bool(verdict.get("overreach")) and not by_work, "unanswered": bool(verdict.get("unanswered")),
        "cites": [Cite(_stance(c, ce), str(ce.unit.source_id), ce.unit.author,
                       attested=ce.unit.kind == INTERVIEW_KIND) for ce in c.evidence],
    }


def regrade(db: Session, claims: list[Claim]) -> dict[str, int]:
    """Recomputes grades from the stored judgements. Returns counts by grade (and 'removed').

    Two passes: claims nothing backs are removed first, so they can't make another
    claim look "Conflicting"."""
    inputs = {c.id: _inputs(c) for c in claims if c.status != ClaimStatus.rejected}
    removed = {cid for cid, i in inputs.items() if i and decide(**i, conflicting=False)[0] is None}
    alive = {cid for cid in inputs if cid not in removed}
    counts: dict[str, int] = {}
    for c in claims:
        i = inputs.get(c.id)
        if i is None:
            continue  # rejected earlier, or not checked yet
        grade, reason = decide(**i, conflicting=any(other in alive for other in (c.conflicts_with or [])))
        system = i["system"]
        if grade is None:
            c.status = ClaimStatus.rejected
            c.grade_reason = reason
            counts["removed"] = counts.get("removed", 0) + 1
            continue
        c.grade = grade
        if not system:
            c.grade_reason = reason
        counts[grade.value] = counts.get(grade.value, 0) + 1
    return counts


# --- asking the model ---------------------------------------------------------


def _passage(u: EvidenceUnit, quote: str) -> str:
    """The cited part of the item with some context around it."""
    text = u.text
    probe = re.sub(r"\s+", " ", quote.strip())[:40].lower()
    flat = re.sub(r"\s+", " ", text)
    at = flat.lower().find(probe) if probe else -1
    if len(flat) <= PASSAGE_CHARS:
        return flat
    start = max(0, (at if at >= 0 else 0) - PASSAGE_CHARS // 3)
    window = flat[start : start + PASSAGE_CHARS]
    return ("… " if start else "") + window + (" …" if start + PASSAGE_CHARS < len(flat) else "")


def _render(n: int, c: Claim, cites: list[ClaimEvidence], source_names: dict) -> str:
    parts = [f'<claim id="C{n}" type="{c.type.value}">', f"Statement: {c.statement}"]
    if c.rationale:
        parts.append(f"Reason given: {c.rationale}")
    for k, ce in enumerate(cites, start=1):
        u = ce.unit
        attrs = {"id": f"C{n}-E{k}", "source": source_names.get(u.source_id, ""), "author": u.author,
                 "date": local_date(u.occurred_at).isoformat() if u.occurred_at else ""}
        head = " ".join(f'{key}="{escape(str(v), quote=True)}"' for key, v in attrs.items() if v)
        parts.append(f"<evidence {head}>\n{guard.fence(_passage(u, ce.quote))}\n</evidence>")
    parts.append("</claim>")
    return "\n".join(parts)


def _batch_key(batch: list[Claim]) -> str:
    return hashlib.sha256("".join(str(c.id) for c in batch).encode()).hexdigest()[:16]


def grade(db: Session, ctx: AgentContext) -> dict[str, int]:
    """Checks every unchecked claim of the run, then grades all of them."""
    skill = skills.load("skeptic")
    sendable = set(sendable_labels())
    with step(db, ctx, "skeptic") as row:
        claims = db.scalars(select(Claim).where(Claim.run_id == ctx.run_id,
                                                Claim.status != ClaimStatus.rejected)).all()
        row.items_in = len(claims)
        to_check = sorted((c for c in claims if not c.grade_reason.startswith(SYSTEM_DATA) and not c.skeptic),
                          key=lambda c: (c.subject.lower(), c.statement))
        # Deal claims across batches like cards, so claims about the same thing (which may disagree)
        # never share a call: the Skeptic judges each claim against its own passages only.
        n_batches = -(-len(to_check) // BATCH)
        batches = [to_check[i::n_batches] for i in range(n_batches)]
        batches = [b for b in batches if not is_done(db, ctx.run_id, "skeptic", _batch_key(b))]

        sent: list[list[tuple[Claim, list[ClaimEvidence]]]] = []
        prompts = []
        for batch in batches:
            items = [(c, [ce for ce in c.evidence if ce.unit.sensitivity in sendable]) for c in batch]
            sent.append(items)
            prompts.append("\n\n".join(_render(n, c, cites, ctx.source_names)
                                       for n, (c, cites) in enumerate(items, start=1)))
        answers = generate_many(ctx, SkepticOut, prompts, agent="skeptic", skill=skill,
                                usage=ctx.usage_for("skeptic"))
        for batch, items, out in zip(batches, sent, tracked(db, ctx, "skeptic", answers, len(batches)), strict=True):
            checks = {ch.claim.strip().upper(): ch for ch in (out.checks if out else [])}
            for n, (c, cites) in enumerate(items, start=1):
                check = checks.get(f"C{n}")
                if check is None:
                    continue  # stays unchecked; shown as "Not checked yet"
                stances = {s.id.strip().upper(): stance_of(s.stance) for s in check.citations}
                for k, ce in enumerate(cites, start=1):
                    ce.stance = stances.get(f"C{n}-E{k}", "unrelated")
                if not check.reason_supported and c.rationale:
                    c.rationale = ""  # never keep a reason the evidence doesn't give
                c.skeptic = {
                    "overreach": check.overreach,
                    "reason_removed": not check.reason_supported,
                    "unanswered": c.grade_reason == "unanswered",
                    "note": check.note.strip()[:300],
                }
            db.commit()
            mark_done(db, ctx.run_id, "skeptic", _batch_key(batch))

        counts = regrade(db, claims)
        db.commit()
        removed = counts.pop("removed", 0)
        row.items_out = sum(counts.values())
        order = [g.value for g in Grade]
        row.summary = (f"Checked {len(to_check)} claims against their passages: "
                       + ", ".join(f"{counts[g]} {g}" for g in order if counts.get(g))
                       + (f"; removed {removed} that nothing backs" if removed else "") + ".")
    return counts | ({"removed": removed} if removed else {})
