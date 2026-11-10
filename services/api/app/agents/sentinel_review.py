"""Sentinel (agent 2), the reviewing half: after the rules have masked and
labelled everything, a model reads each item and flags sensitive context the
rules can't see ("Dev has a rough time at home, go easy on him").

It can only make a label stricter, never looser; the rules stay the floor.
It only sees items whose label may go to the model at all, and each item is
reviewed once per skill version.
"""

import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, gatekeeper, guard
from app.agents import skills
from app.agents.base import AgentContext, generate_many, step, tracked
from app.agents.evidence import packet_units
from app.db.models import EvidenceUnit, Sensitivity
from app.llm import LLMUnavailable
from app.sentinel import strictest

log = logging.getLogger(__name__)
BATCH = 25
MAX_CHARS = 1_500


class Flag(BaseModel):
    id: str = Field(description="item id, e.g. E4")
    label: str = Field(description='"restricted" or "confidential"')
    reason: str = Field(description="short reason a person can check")


class ReviewOut(BaseModel):
    flags: list[Flag]


def _render(n: int, u: EvidenceUnit) -> str:
    text = u.text if len(u.text) <= MAX_CHARS else u.text[:MAX_CHARS] + " …"
    head = f'<evidence id="E{n}" kind="{u.kind}" label="{u.sensitivity.value}">'
    return f"{head}\n{guard.fence(u.title)}\n{guard.fence(text)}\n</evidence>"


def review(db: Session, ctx: AgentContext) -> int:
    """Reviews unreviewed items. Returns how many labels were raised."""
    skill = skills.load("sentinel_review")
    marker = f"v{skill.version}"
    units = [u for u in packet_units(db, ctx.principal, ctx.project_id)
             if (u.meta or {}).get("sentinel_review") != marker]
    raised = 0
    batches = [units[i : i + BATCH] for i in range(0, len(units), BATCH)]
    prompts = ["\n\n".join(_render(n, u) for n, u in enumerate(batch, start=1)) for batch in batches]
    with step(db, ctx, "sentinel") as row:
        row.items_in = len(units)
        answers = generate_many(ctx, ReviewOut, prompts, agent="sentinel_review", skill=skill,
                                usage=ctx.usage_for("sentinel"))
        try:
            for batch, out in zip(batches, tracked(db, ctx, "sentinel", answers, len(batches)), strict=True):
                if out is not None:  # otherwise rule labels stand, and the batch is reviewed again next run
                    raised += _apply(db, ctx, batch, out, marker)
        except LLMUnavailable as e:
            log.warning("sentinel review stopped (%s); rule labels stand", e)
        row.items_out = raised
        row.summary = f"Reviewed {len(units)} items after the rules; raised {raised} labels."
    return raised


def _apply(db: Session, ctx: AgentContext, batch: list[EvidenceUnit], out: ReviewOut, marker: str) -> int:
    """Applies one batch's flags, only ever raising a label, and marks the batch reviewed."""
    raised = 0
    for f in out.flags:
        try:
            unit = batch[int(f.id.strip().upper().lstrip("E")) - 1]
            wanted = Sensitivity(f.label.strip().lower())
        except (ValueError, IndexError):
            continue
        new = strictest(unit.sensitivity, wanted)
        if new == unit.sensitivity:
            continue  # never lower, and nothing to do when it's already this strict
        old = unit.sensitivity
        unit.sensitivity = new
        reasons = list((unit.meta or {}).get("label_reasons", []))
        unit.meta = {**(unit.meta or {}), "label_reasons": [*reasons, f"AI review: {f.reason[:200]}"]}
        audit.record(db, actor_id=None, action="evidence.relabel.ai", object_type="evidence",
                     object_id=unit.id, project_id=ctx.project_id, old=old.value, new=new.value,
                     reason=f.reason[:200])
        db.commit()
        gatekeeper.relabel_evidence(db, unit, old)
        raised += 1
    for u in batch:
        u.meta = {**(u.meta or {}), "sentinel_review": marker}
    db.commit()
    return raised
