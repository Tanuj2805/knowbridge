"""Shared machinery for agents: run steps, bundles, resumable progress, and
saving claims whose quotes really appear in the evidence."""

import hashlib
import logging
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import evidence, skills
from app.agents.evidence import Packet
from app.config import get_settings
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimType,
    EvidenceUnit,
    Run,
    RunStep,
    Source,
)
from app.gatekeeper.policy import Principal
from app.llm import gateway
from app.sentinel import content_hash, strictest

log = logging.getLogger(__name__)
BUNDLE_CHARS = 6_000  # bigger bundles made the model skim: fewer claims per packet


# --- what extraction agents return ---------------------------------------


class Cite(BaseModel):
    id: str = Field(description="evidence id, e.g. E3")
    quote: str = Field(description="exact words copied from that evidence, 6-200 characters")


class DraftClaim(BaseModel):
    type: str = Field(description="claim type, from the list in your instructions")
    statement: str = Field(description="one self-contained sentence with names, dates and specifics")
    rationale: str = Field(default="", description="why, only if the evidence says so; otherwise empty")
    alternatives: list[str] = Field(default_factory=list, description="options considered and rejected, if stated")
    subject: str = Field(description="the ONE thing it is about, in 1-5 words, e.g. 'payment confirmation'; "
                                     "a claim covering several modules must be split into one claim each")
    owner: str = Field(default="", description="person responsible, only if the evidence names one")
    due: str = Field(default="", description="deadline as YYYY-MM-DD, only if stated")
    when: str = Field(default="", description="date it was decided/raised as YYYY-MM-DD, from the evidence")
    impact: int = Field(default=2, description="1 low, 2 medium, 3 high: how much a newcomer needs to know this")
    answered: bool = Field(default=True, description="for open_question only: false if nobody answered it")
    evidence: list[Cite] = Field(description="1 to 4 citations that state this")


class ExtractionOut(BaseModel):
    claims: list[DraftClaim]


# --- context --------------------------------------------------------------


@dataclass
class AgentContext:
    run_id: uuid.UUID
    project_id: uuid.UUID
    principal: Principal
    brief: str
    source_names: dict[uuid.UUID, str]
    budget: gateway.Budget
    usage: dict[str, gateway.Usage] = field(default_factory=dict)

    def usage_for(self, agent: str) -> gateway.Usage:
        return self.usage.setdefault(agent, gateway.Usage())


def context_for(db: Session, run: Run, principal: Principal) -> AgentContext:
    from app.config import get_settings

    s = get_settings()
    names = {sid: name for sid, name in db.execute(
        select(Source.id, Source.name).where(Source.project_id == run.project_id)).all()}
    return AgentContext(
        run_id=run.id,
        project_id=run.project_id,
        principal=principal,
        brief=evidence.project_brief(db, run.project_id),
        source_names=names,
        budget=gateway.Budget(max_calls=s.run_max_llm_calls, max_tokens=s.run_max_tokens),
    )


@contextmanager
def step(db: Session, ctx: AgentContext, agent: str) -> Iterator[RunStep]:
    """Records one agent's work in run_steps (shown live in the run view)."""
    row = db.scalar(select(RunStep).where(RunStep.run_id == ctx.run_id, RunStep.agent == agent))
    if row is None:
        row = RunStep(run_id=ctx.run_id, agent=agent, status="running")
        db.add(row)
    row.status, row.error = "running", ""
    db.commit()
    usage = ctx.usage_for(agent)
    try:
        yield row
        row.status = "done"
    except Exception as e:
        row.status = "paused" if e.__class__.__name__ == "RetryLater" else "failed"
        row.error = str(e)[:500]
        raise
    finally:
        row.llm_calls = usage.calls
        row.tokens = usage.tokens
        row.finished_at = datetime.now(UTC) if row.status in ("done", "failed") else None
        db.commit()


# --- asking the model, several calls at a time ------------------------------


def generate_many[T: BaseModel](
    ctx: AgentContext, schema: type[T], prompts: list[str], *, agent: str, skill: skills.Skill,
    usage: gateway.Usage,
) -> Iterator[T | None]:
    """Answers for each prompt, in order; None where the answer never matched the schema.

    Up to LLM_PARALLEL calls run at once (the gateway's pacing and rate-limit handling
    still apply). Each call gets its own database session for the answer cache, so the
    caller's session stays on the caller's thread.
    """
    from app.db.session import SessionLocal

    def ask(prompt: str) -> T | None:
        with SessionLocal() as db:
            try:
                return gateway.generate(
                    db, schema, agent=agent, version=skill.version, tier=skill.tier, system=skill.instructions,
                    prompt=prompt, thinking=skill.thinking, budget=ctx.budget, usage=usage,
                ).value
            except gateway.AgentOutputInvalid:
                log.warning("%s: an answer never matched the schema; skipping it", agent)
                return None

    parallel = max(1, get_settings().llm_parallel)
    if parallel == 1 or len(prompts) <= 1:
        for prompt in prompts:
            yield ask(prompt)
        return
    pool = ThreadPoolExecutor(max_workers=parallel, thread_name_prefix=f"llm-{agent}")
    try:
        yield from pool.map(ask, prompts)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)  # a pause or error stops the calls not yet started


# --- bundles and progress -------------------------------------------------


def bundles(packets: list[Packet], limit: int = BUNDLE_CHARS) -> list[list[Packet]]:
    """Packs small packets into one call each, keeping packet boundaries."""
    out: list[list[Packet]] = []
    cur: list[Packet] = []
    size = 0
    for pk in sorted(packets, key=lambda p: p.key):
        if cur and size + pk.size > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(pk)
        size += pk.size
    if cur:
        out.append(cur)
    return out


def bundle_key(bundle: list[Packet]) -> str:
    h = hashlib.sha256()
    for pk in bundle:
        h.update(pk.key.encode())
        for u in pk.units:
            h.update(u.content_hash.encode())
    return h.hexdigest()[:16]


def render_bundle(ctx: AgentContext, bundle: list[Packet]) -> tuple[str, dict[str, EvidenceUnit]]:
    parts, ids, n = [], {}, 1
    for pk in bundle:
        text, local = evidence.render(pk, ctx.source_names, start=n)
        parts.append(f'<packet title="{pk.title}">\n{text}\n</packet>')
        ids.update(local)
        n += len(local)
    return "\n\n".join(parts), ids


def is_done(db: Session, run_id: uuid.UUID, agent: str, key: str) -> bool:
    run = db.get(Run, run_id)
    return key in (run.state or {}).get("done", {}).get(agent, [])


def mark_done(db: Session, run_id: uuid.UUID, agent: str, key: str) -> None:
    run = db.get(Run, run_id)
    state = dict(run.state or {})
    done = dict(state.get("done", {}))
    done[agent] = [*done.get(agent, []), key]
    state["done"] = done
    run.state = state
    db.commit()


def report(db: Session, run_id: uuid.UUID, agent: str, done: int, total: int) -> None:
    """How far an agent has got ("12 of 33 calls"), for the live run view."""
    run = db.get(Run, run_id)
    state = dict(run.state or {})
    state["progress"] = {**state.get("progress", {}), agent: {"done": done, "total": total}}
    run.state = state
    db.commit()


def tracked[T](db: Session, ctx: AgentContext, agent: str, answers: Iterator[T], total: int,
               already: int = 0) -> Iterator[T]:
    """Passes answers through, reporting progress as each one arrives."""
    report(db, ctx.run_id, agent, already, already + total)
    for n, answer in enumerate(answers, start=1):
        report(db, ctx.run_id, agent, already + n, already + total)
        yield answer


# --- saving claims --------------------------------------------------------


def _date(s: str) -> datetime | None:
    try:
        return datetime.combine(date.fromisoformat(s.strip()[:10]), datetime.min.time(), UTC) if s else None
    except ValueError:
        return None


def save_claim(
    db: Session,
    ctx: AgentContext,
    agent: str,
    draft: DraftClaim,
    ids: dict[str, EvidenceUnit],
    allowed_types: set[ClaimType],
) -> Claim | None:
    """Saves a draft claim if its type is allowed for this agent and at least one
    citation's quote really appears in the cited item. Returns None otherwise."""
    try:
        ctype = ClaimType(draft.type.strip().lower().replace(" ", "_"))
    except ValueError:
        return None
    if ctype not in allowed_types or not draft.statement.strip():
        return None
    cites = []
    for c in draft.evidence[:4]:
        unit = ids.get(c.id.strip().upper())
        if unit is not None and evidence.find_quote(unit, c.quote):
            cites.append((unit, c.quote.strip()))
    if not cites:
        return None
    claim = Claim(
        project_id=ctx.project_id,
        run_id=ctx.run_id,
        type=ctype,
        statement=draft.statement.strip()[:1000],
        rationale=draft.rationale.strip()[:2000],
        alternatives=[a.strip() for a in draft.alternatives if a.strip()][:5],
        subject=draft.subject.strip()[:300],
        owner_name=draft.owner.strip()[:200],
        due_date=(_date(draft.due) or None) and _date(draft.due).date(),
        valid_from=_date(draft.when) or min((u.occurred_at for u, _ in cites if u.occurred_at), default=None),
        impact=min(3, max(1, draft.impact or 2)),
        created_by_agent=agent,
        sensitivity=strictest(*(u.sensitivity for u, _ in cites)),
    )
    if ctype == ClaimType.open_question and not draft.answered:
        claim.grade_reason = "unanswered"
    db.add(claim)
    db.flush()
    seen = set()
    for unit, quote in cites:
        if unit.id in seen:
            continue
        seen.add(unit.id)
        db.add(ClaimEvidence(claim_id=claim.id, evidence_id=unit.id, quote=quote, quote_hash=content_hash(quote)))
    return claim


def run_extraction(
    db: Session,
    ctx: AgentContext,
    agent: str,
    packets: list[Packet],
    allowed: set[ClaimType],
) -> tuple[int, int]:
    """Runs one extraction agent over its packets. Returns (claims kept, drafts dropped).

    Prompts are prepared here, the model calls run in parallel, and claims are saved
    here as each answer arrives, so a paused run resumes after the last saved bundle."""
    skill = skills.load(agent)
    todo = []
    for bundle in bundles(packets):
        key = bundle_key(bundle)
        if not is_done(db, ctx.run_id, agent, key):
            text, ids = render_bundle(ctx, bundle)
            todo.append((key, ids, f"{ctx.brief}\n\n{text}"))
    answers = generate_many(ctx, ExtractionOut, [prompt for _, _, prompt in todo], agent=agent, skill=skill,
                            usage=ctx.usage_for(agent))
    kept = dropped = 0
    finished = len(bundles(packets)) - len(todo)  # bundles done before a pause
    for (key, ids, _), out in zip(todo, tracked(db, ctx, agent, answers, len(todo), finished), strict=True):
        for draft in out.claims if out else []:
            if save_claim(db, ctx, agent, draft, ids, allowed):
                kept += 1
            else:
                dropped += 1
        db.commit()
        mark_done(db, ctx.run_id, agent, key)
    return kept, dropped
