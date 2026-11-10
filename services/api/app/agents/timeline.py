"""Timeline Builder (agent 6): compares claims of the same kind and records how
they relate.

  - duplicates are merged into one claim that keeps all their evidence
  - a later claim that changes an earlier one marks it replaced (superseded_by,
    valid_to), so the ledger shows today's state with its history underneath
  - claims that disagree are linked as conflicts, for the Skeptic and the reviewer

A first pass names duplicates and suggests replacements and conflicts; a second
look checks each suggested pair on its own (first passes over-report: "both can be
true" is the usual answer). Code then checks what's left (the two claims must share
a subject, a replacement must go forward in time) and applies it.
"""

import re
from collections import Counter
from datetime import UTC, datetime
from itertools import combinations

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import skills
from app.agents.base import AgentContext, generate_many, is_done, mark_done, step, tracked
from app.agents.evidence import local_date, sendable_labels
from app.agents.facts import SYSTEM_DATA
from app.db.models import Claim, ClaimStatus, ClaimType
from app.sentinel import strictest

# Kinds compared with each other: a fact may come out as a risk from one agent and a blocker from another.
FAMILIES: dict[str, set[ClaimType]] = {
    "decisions": {ClaimType.decision},
    "owners": {ClaimType.owner},
    "dependencies": {ClaimType.dependency, ClaimType.contact},
    "risks": {ClaimType.risk, ClaimType.blocker, ClaimType.recurring_problem},
    "follow-ups": {ClaimType.open_question, ClaimType.next_action},
}
CHUNK = 120  # claims per call; sorted by subject, so related claims share a chunk
MAX_PAIRS = 60  # pairs per second-look call
MAX_NUMBER_PAIRS = 20  # of those, proposed by code (different values, shared rare words)
MIN_PAIR_SCORE = 0.6  # e.g. sharing "payment", "polling" and "seconds"
_EARLIEST = datetime.min.replace(tzinfo=UTC)
_STOP = {"the", "and", "for", "with", "app", "web", "project", "team", "page", "feature", "module", "system",
         "every", "since", "from", "that", "this", "uses", "used", "into", "after", "before", "until", "their",
         "have", "been", "will", "only", "also", "when", "which", "about"}


def _words(text: str, min_len: int = 3) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= min_len and w not in _STOP}


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Names, not values: Jira keys (KCT-102), PR/issue numbers (#42, PR 42), commit hashes.
_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b|#\d+|\b(?:PR|issue|pull request)s?\s+\d+\b|\b[0-9a-f]{7,40}\b",
                         re.I)


def values(text: str) -> set[str]:
    """The numbers in a statement that are values (dates, amounts, limits), not identifiers."""
    return set(_NUMBER.findall(_IDENTIFIER.sub(" ", text)))


def same_numbers(a: Claim, b: Claim) -> bool:
    """False when the two statements carry different values (3 vs 5 events, 15 vs 31 Dec):
    those may be a conflict, and merging them would hide it. Extra detail is fine:
    "2 Dec" and "2 Dec 2026" can still merge, and ticket numbers don't count."""
    na, nb = values(a.statement), values(b.statement)
    return na <= nb or nb <= na


_TICKET = re.compile(r"\b([A-Z][A-Z0-9]+)-(\d+)\b|#(\d+)")
_NOT_TICKETS = {"UTF", "SHA", "ISO", "TLS", "HTTP", "COVID", "MP", "PDF"}


def tickets(c: Claim) -> set[str]:
    """Ticket and PR names the claim mentions: KCT-149, PR #42."""
    found = set()
    for key, number, hash_number in _TICKET.findall(f"{c.subject} {c.statement}"):
        if hash_number:
            found.add(f"#{hash_number}")
        elif key not in _NOT_TICKETS:
            found.add(f"{key}-{number}")
    return found


def different_tickets(a: Claim, b: Claim) -> bool:
    """Both name tickets, and not the same ones: KCT-149 and KCT-39 are different bugs,
    so they can be neither duplicates nor a conflict, however alike they sound."""
    ta, tb = tickets(a), tickets(b)
    return bool(ta and tb and not ta & tb)


def related(a: Claim, b: Claim) -> bool:
    """A cheap check that two claims could be about the same thing, before the second
    look judges them: their subjects share a word, or their statements share two
    ("payment polling … seconds"). "Backups failing" and "CI build failing" share neither."""
    if different_tickets(a, b):
        return False
    sa, sb = _words(a.subject), _words(b.subject)
    if not sa or not sb or sa & sb:
        return True
    return len(_words(a.statement, 4) & _words(b.statement, 4)) >= 2


class Group(BaseModel):
    ids: list[str] = Field(description="ids of claims that state the same fact, e.g. ['C3', 'C17']")


class Replacement(BaseModel):
    old: str = Field(description="id of the earlier claim")
    new: str = Field(description="id of the later claim that changes it")
    note: str = Field(default="", description="what changed, in a few words")


class Conflict(BaseModel):
    a: str
    b: str
    about: str = Field(default="", description="what they disagree on, in a few words")


class TimelineOut(BaseModel):
    duplicates: list[Group]
    replaced: list[Replacement]
    conflicts: list[Conflict]


class PairVerdict(BaseModel):
    id: str = Field(description="pair id, e.g. P2")
    relation: str = Field(description='"duplicate", "replaced", "conflict", "compatible" or "unrelated"')
    newer: str = Field(default="", description='for "replaced" only: "a" or "b"')


class PairsOut(BaseModel):
    pairs: list[PairVerdict]


def _line(n: int, c: Claim) -> str:
    when = local_date(c.valid_from).isoformat() if c.valid_from else "undated"
    return f"C{n} | {when} | {c.subject or '-'} | {c.statement}"


def _keep_first(c: Claim) -> tuple:
    """Which duplicate survives: system data first, then the best-evidenced, most complete one."""
    return (c.grade_reason.startswith(SYSTEM_DATA), len(c.evidence), c.impact, bool(c.rationale), len(c.statement))


def _absorb(db: Session, keep: Claim, dup: Claim) -> None:
    have = {ce.evidence_id for ce in keep.evidence}
    for ce in list(dup.evidence):
        if ce.evidence_id not in have:
            keep.evidence.append(ce)  # moves the citation; the rest go with the duplicate
            have.add(ce.evidence_id)
    keep.impact = max(keep.impact, dup.impact)
    keep.rationale = keep.rationale or dup.rationale
    keep.owner_name = keep.owner_name or dup.owner_name
    keep.due_date = keep.due_date or dup.due_date
    keep.alternatives = list(dict.fromkeys([*(keep.alternatives or []), *(dup.alternatives or [])]))[:5]
    if dup.valid_from and (keep.valid_from is None or dup.valid_from < keep.valid_from):
        keep.valid_from = dup.valid_from
    keep.sensitivity = strictest(keep.sensitivity, dup.sensitivity)
    db.delete(dup)


def _merge(db: Session, chunk: list[Claim], out: TimelineOut) -> tuple[int, list[tuple[Claim, Claim]]]:
    """Merges the duplicate groups. Returns how many were merged, and the suggested
    replacements and conflicts (as pairs) for the second look."""
    ids = {f"C{n}": c for n, c in enumerate(chunk, start=1)}
    into: dict[str, Claim] = {}  # ids of merged claims -> the claim they were merged into

    def get(ref: str) -> Claim | None:
        key = ref.strip().upper()
        return into.get(key) or ids.get(key)

    merged = 0
    held_back: list[tuple[Claim, Claim]] = []  # "duplicates" whose numbers differ: a possible conflict
    for group in out.duplicates:
        members = list({c.id: c for c in (get(r) for r in group.ids) if c is not None}.values())
        if len(members) < 2:
            continue
        keep = max(members, key=_keep_first)
        for c in members:
            if c is keep or different_tickets(keep, c):
                continue  # claims about different tickets are never the same fact
            if not same_numbers(keep, c):
                held_back.append((keep, c))
                continue
            _absorb(db, keep, c)
            into.update({ref: keep for ref, claim in ids.items() if claim is c})
            merged += 1

    pairs, seen = [], set()
    for a, b in held_back:
        if a.id != b.id and frozenset((a.id, b.id)) not in seen:
            seen.add(frozenset((a.id, b.id)))
            pairs.append((a, b))
    for a_ref, b_ref in [(r.old, r.new) for r in out.replaced] + [(k.a, k.b) for k in out.conflicts]:
        a, b = get(a_ref), get(b_ref)
        if a is None or b is None or a is b or not related(a, b) or frozenset((a.id, b.id)) in seen:
            continue
        seen.add(frozenset((a.id, b.id)))
        pairs.append((a, b))

    # First passes miss some: "at most 3 events" vs "a maximum of 5 events" was never suggested.
    alive = list({get(ref).id: get(ref) for ref in ids}.values())  # each claim once, merged ones as their keeper
    pairs += _number_pairs(alive, seen)[: max(0, MAX_PAIRS - len(pairs))]
    return merged, pairs


def _number_pairs(claims: list[Claim], seen: set) -> list[tuple[Claim, Claim]]:
    """Pairs that carry different values and probably share a subject, best first.

    Shared words are weighted by rarity: two claims both about "polling" or the "free pass"
    rank high; sharing "bug" or "sprint" (in every Jira claim) counts for little. Claims read
    from system data are separate facts by construction (one per overdue card) and are skipped."""
    claims = [c for c in claims if not c.grade_reason.startswith(SYSTEM_DATA)]
    words = {c.id: _words(c.subject) | _words(c.statement, 4) for c in claims}
    df = Counter(w for ws in words.values() for w in ws)
    scored = []
    for a, b in combinations(claims, 2):
        if frozenset((a.id, b.id)) in seen or same_numbers(a, b) or different_tickets(a, b):
            continue
        score = sum(1 / df[w] for w in words[a.id] & words[b.id])
        if score >= MIN_PAIR_SCORE:
            scored.append((score, a, b))
    scored.sort(key=lambda t: -t[0])
    return [(a, b) for _, a, b in scored[:MAX_NUMBER_PAIRS]]


def _pair_text(n: int, a: Claim, b: Claim) -> str:
    def side(tag: str, c: Claim) -> str:
        when = local_date(c.valid_from).isoformat() if c.valid_from else "undated"
        return f"  {tag} ({when}): {c.statement}"

    return f"P{n}\n{side('a', a)}\n{side('b', b)}"


def relation_of(v: PairVerdict) -> tuple[str, str]:
    """(relation, newer) read leniently: models write "replaced: b", "Conflict." and the like."""
    text = v.relation.strip().lower()
    for word in ("duplicate", "replaced", "conflict", "compatible", "unrelated"):
        if text.startswith(word[:6]):
            newer = v.newer.strip().lower()[:1] or (text.rsplit(":", 1)[-1].strip()[:1] if ":" in text else "")
            return word, newer if newer in ("a", "b") else ""
    return "unrelated", ""


def _link(db: Session, pairs: list[tuple[Claim, Claim]], verdicts: PairsOut) -> tuple[int, int, int]:
    """Applies the pairs the second look confirmed. Returns (merged, replaced, conflicts)."""
    by_id = {v.id.strip().upper(): v for v in verdicts.pairs}
    merged = replaced = conflicts = 0
    gone: set = set()
    for n, (a, b) in enumerate(pairs, start=1):
        v = by_id.get(f"P{n}")
        if v is None or a.id in gone or b.id in gone or different_tickets(a, b):
            continue
        relation, newer = relation_of(v)
        if relation == "duplicate":
            if not same_numbers(a, b):
                continue  # different numbers are never merged; a person sees both
            keep, dup = (a, b) if _keep_first(a) >= _keep_first(b) else (b, a)
            _absorb(db, keep, dup)
            gone.add(dup.id)
            merged += 1
        elif relation == "replaced":
            old, new = (b, a) if newer == "a" else (a, b)
            if old.superseded_by or (old.valid_from and new.valid_from and old.valid_from > new.valid_from):
                continue  # a replacement has to come later
            old.superseded_by = new.id
            old.valid_to = new.valid_from
            replaced += 1
        elif relation == "conflict" and b.id not in (a.conflicts_with or []):
            a.conflicts_with = [*(a.conflicts_with or []), b.id]
            b.conflicts_with = [*(b.conflicts_with or []), a.id]
            conflicts += 1
    return merged, replaced, conflicts


def build(db: Session, ctx: AgentContext) -> tuple[int, int, int]:
    """Returns (duplicates merged, claims marked replaced, conflicts found)."""
    skill, check = skills.load("timeline_builder"), skills.load("timeline_check")
    sendable = set(sendable_labels())
    with step(db, ctx, "timeline") as row:
        claims = db.scalars(select(Claim).where(Claim.run_id == ctx.run_id,
                                                Claim.status != ClaimStatus.rejected)).all()
        row.items_in = len(claims)
        chunks: list[tuple[str, list[Claim]]] = []
        for family, types in FAMILIES.items():
            members = sorted((c for c in claims if c.type in types and c.sensitivity in sendable),
                             key=lambda c: (c.subject.lower(), c.valid_from or _EARLIEST))
            for i in range(0, len(members), CHUNK):
                key = f"{family}:{i // CHUNK}"
                chunk = members[i : i + CHUNK]
                if len(chunk) > 1 and not is_done(db, ctx.run_id, "timeline", key):
                    chunks.append((key, chunk))

        # First pass: duplicates are merged now; replacements and conflicts are only suggestions.
        prompts = ["\n".join(_line(n, c) for n, c in enumerate(chunk, start=1)) for _, chunk in chunks]
        answers = generate_many(ctx, TimelineOut, prompts, agent="timeline_builder", skill=skill,
                                usage=ctx.usage_for("timeline"))
        merged = suggested = 0
        second: list[tuple[str, list[tuple[Claim, Claim]]]] = []
        for (key, chunk), out in zip(chunks, tracked(db, ctx, "timeline", answers, len(chunks)), strict=True):
            pairs: list[tuple[Claim, Claim]] = []
            if out is not None:
                n, pairs = _merge(db, chunk, out)
                merged += n
                db.commit()
            suggested += len(pairs)
            if pairs:
                second.append((key, pairs))
            else:
                mark_done(db, ctx.run_id, "timeline", key)

        # Second look: first passes over-report, so every suggested pair is checked on its own.
        prompts = ["\n\n".join(_pair_text(n, a, b) for n, (a, b) in enumerate(pairs, start=1))
                   for _, pairs in second]
        verdicts = generate_many(ctx, PairsOut, prompts, agent="timeline_check", skill=check,
                                 usage=ctx.usage_for("timeline"))
        replaced = conflicts = 0
        checked = tracked(db, ctx, "timeline", verdicts, len(second), already=len(chunks))
        for (key, pairs), v in zip(second, checked, strict=True):
            if v is not None:
                m, r, k = _link(db, pairs, v)
                merged, replaced, conflicts = merged + m, replaced + r, conflicts + k
            db.commit()
            mark_done(db, ctx.run_id, "timeline", key)

        row.items_out = len(claims) - merged
        row.summary = (f"Compared {len(claims)} claims: merged {merged} duplicates, marked {replaced} as replaced "
                       f"by a later change, found {conflicts} conflicts"
                       + (f" (a second look kept {replaced + conflicts} of {suggested} suggestions)" if suggested
                          else "") + ".")
    return merged, replaced, conflicts
