"""Agents 3-5: the Decision Miner, the Ownership & Dependency Mapper and the
Risk & Blocker Detector. Each reads the packets the Scout sent it and writes
draft claims; the last two also add claims read straight from system data
(git history, CI, pull requests, task cards).
"""

from sqlalchemy.orm import Session

from app.agents import facts
from app.agents.base import AgentContext, bundles, is_done, mark_done, run_extraction, step
from app.agents.evidence import Packet
from app.agents.scout import SPECIALISTS
from app.db.models import ClaimType

ALLOWED: dict[str, set[ClaimType]] = {
    "decision_miner": {ClaimType.decision},
    "ownership_mapper": {ClaimType.owner, ClaimType.dependency, ClaimType.contact},
    "risk_detector": {ClaimType.risk, ClaimType.blocker, ClaimType.recurring_problem,
                      ClaimType.open_question, ClaimType.next_action},
}
FROM_DATA = {"ownership_mapper": facts.ownership, "risk_detector": facts.risks}


def extract(db: Session, ctx: AgentContext, agent: str, packets: list[Packet],
            routes: dict[str, list[str]]) -> int:
    """Runs one extraction agent. Returns how many claims it kept."""
    mine = [pk for pk in packets if agent in routes.get(pk.key, SPECIALISTS)]
    with step(db, ctx, agent) as row:
        row.items_in = len(mine)
        from_data = 0
        if agent in FROM_DATA and not is_done(db, ctx.run_id, agent, "facts"):
            from_data = FROM_DATA[agent](db, ctx, agent)
            db.commit()
            mark_done(db, ctx.run_id, agent, "facts")
        kept, dropped = run_extraction(db, ctx, agent, mine, ALLOWED[agent])
        row.items_out = kept + from_data
        row.summary = (f"Read {len(mine)} packets in {len(bundles(mine))} calls: {kept} claims kept"
                       + (f", {dropped} dropped (quote not found or wrong type)" if dropped else "")
                       + (f"; {from_data} more from system data" if from_data else "") + ".")
    return kept + from_data
