"""Scout (agent 1): plans which evidence packets each extraction agent reads.

Connectors (the Scout's tools) already collected everything; this step decides
which specialist reads what, so agents read focused evidence. It never drops a
packet: one the model calls noise still goes to the Risk Detector, and if the
model fails, every packet goes to every specialist. Missing something matters
more than an extra read.
"""

import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import skills
from app.agents.base import AgentContext, report, step
from app.agents.evidence import Packet
from app.llm import LLMUnavailable, gateway

log = logging.getLogger(__name__)

SPECIALISTS = ("decision_miner", "ownership_mapper", "risk_detector")
INDEX_BATCH = 40
PREVIEW_CHARS = 240
# Some packets have an obvious reader, whatever the model says.
ALWAYS = {"ownership": {"ownership_mapper"}, "ci": {"risk_detector"}}
NOISE_READER = "risk_detector"  # what "noise" still goes to: delays and promises hide in short chat


class Route(BaseModel):
    packet: str = Field(description="packet id, e.g. P3")
    agents: list[str] = Field(description="specialists who should read it; empty for noise")
    reason: str = Field(default="", description="a few words on why")


class ScoutOut(BaseModel):
    routes: list[Route]


def _index_line(n: int, pk: Packet) -> str:
    first = " ".join((pk.units[0].text if pk.units else "").split())[:PREVIEW_CHARS]
    return f"P{n} | {pk.kind} | {pk.title} | {len(pk.units)} items | {first}"


def plan(db: Session, ctx: AgentContext, packets: list[Packet]) -> dict[str, list[str]]:
    """Returns {packet key: [specialists]}; an empty list means "skip"."""
    routes: dict[str, set[str]] = {pk.key: set(SPECIALISTS) for pk in packets}  # fail open
    skill = skills.load("scout")
    with step(db, ctx, "scout") as row:
        row.items_in = len(packets)
        calls = -(-len(packets) // INDEX_BATCH)
        for i in range(0, len(packets), INDEX_BATCH):
            report(db, ctx.run_id, "scout", i // INDEX_BATCH, calls)
            batch = packets[i : i + INDEX_BATCH]
            index = "\n".join(_index_line(n, pk) for n, pk in enumerate(batch, start=1))
            try:
                out = gateway.generate(
                    db, ScoutOut, agent="scout", version=skill.version, tier=skill.tier,
                    system=skill.instructions, prompt=f"{ctx.brief}\n\nPacket index:\n{index}",
                    thinking=skill.thinking, budget=ctx.budget, usage=ctx.usage_for("scout"),
                ).value
            except (gateway.AgentOutputInvalid, LLMUnavailable) as e:
                log.warning("scout: keeping every packet for this batch (%s)", e)
                continue
            for r in out.routes:
                try:
                    pk = batch[int(r.packet.strip().upper().lstrip("P")) - 1]
                except (ValueError, IndexError):
                    continue
                routes[pk.key] = {a for a in r.agents if a in SPECIALISTS}
        report(db, ctx.run_id, "scout", calls, calls)
        noise = 0
        for pk in packets:
            routes[pk.key] |= ALWAYS.get(pk.kind, set())
            if not routes[pk.key]:
                # Nothing is dropped: models have called "third attempt at the double-registration
                # bug" and "logos?? … aaj shaam tak, promise" noise. Skipping saves little; missing hurts.
                routes[pk.key] = {NOISE_READER}
                noise += 1
        row.items_out = len(packets)
        row.summary = (f"{len(packets)} packets: {noise} looked like noise (Risk Detector only). "
                       + ", ".join(f"{a.replace('_', ' ')} {sum(1 for v in routes.values() if a in v)}"
                                   for a in SPECIALISTS))
    return {k: sorted(v) for k, v in routes.items()}
