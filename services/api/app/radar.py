"""Knowledge Risk Radar: where a project's knowledge sits with one person.

For one reader it:

  1. takes the latest claims they may see and puts them into areas, the parts
     of the project people own ("Payments", "Screening tests", "Firebase");
  2. collects who holds each area's knowledge from four signals:
       - ownership: owner, dependency and contact claims that name someone
       - tickets:   assignees of the cards and issues the area's claims cite
       - code:      authors of commits that touched files named after the area
       - talk:      authors of the messages, docs and comments the claims cite
  3. turns those into shares per person, and grades each area: high risk when
     one person holds most of it and nobody else holds a meaningful part.

Areas: claim subjects are free text written by the agents, and on real ticket
data many of them name a status ("Stuck bug KCT-144", "Overdue deadline") rather
than a part of the product. So after each "Build claims" run a model groups the
distinct subjects into 6 to 15 areas once (`group_with_model`, a background job);
the grouping is stored on the run. The model only names and groups: every share
and grade is computed here, in code. When no model is available the subjects are
grouped by the words they share instead (`group_by_words`).

Names differ between tools ("aarav-m" on GitHub, "Aarav" in chat, "Aarav Mehta"
in Jira), so every name is matched to a project member first; names that match
nobody (bots, people outside the project) are left out.
"""

import hashlib
import logging
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import gatekeeper, guard, llm
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    EvidenceUnit,
    Handover,
    HandoverStatus,
    Membership,
    Run,
    RunStatus,
    Source,
    User,
)
from app.gatekeeper.policy import Principal

log = logging.getLogger(__name__)

# How much each kind of signal counts towards someone's share of an area.
WEIGHTS = {"ownership": 3.0, "tickets": 2.0, "code": 1.0, "talk": 1.0}
HIGH_SHARE = 0.75      # one person holds this much or more ...
BACKUP_SHARE = 0.20    # ... and nobody else holds at least this much
MEDIUM_SHARE = 0.55
MIN_WEIGHT = 4.0       # an area needs this much signal before it is graded
CAPTURE_KIND = "capture"
STATE_KEY = "radar_areas"  # where a run keeps its model-made grouping
MAX_SUBJECTS = 400     # most-cited subjects sent to the model

OWNERSHIP_TYPES = {ClaimType.owner, ClaimType.dependency, ClaimType.contact}
TICKET_KINDS = {"card", "issue"}
TALK_KINDS = {"message", "doc_section", "meeting_segment", "card_comment", "issue_comment", "pr_comment",
              "pull_request", "doc_chunk"}

# Words that say what kind of thing a subject is, or what state it's in, not which part of the project.
_GENERIC = set("""
a an and the of on in for to with by at from as is are was be its it this that our their his her not no
owner owners ownership owns owned own dependency dependencies depends depend contact contacts bug bugs fix fixes
feature features job jobs page pages account accounts project knowledge key keys issue issues task tasks
setup management process logic flow list system systems team current new plan plans work card cards data
config configuration implementation access support script scripts file files code app application service
services tool tools thing things update updates change changes problem problems risk risks blocker blockers
question questions action actions next decision decisions recurring item items person people role roles via
assigned responsible responsibility handling handle manages managed managing maintains maintenance
stuck stalled blocked overdue pending unassigned unresolved resolved missing delayed delay late incomplete
failure failed failing broken open closed done status state progress review reviews merge merged deadline due
date dates time week weeks sprint sprints epic epics story stories ticket tickets test tests testing tested
handover handovers meeting meetings mentorship consultation creation hack usage strategy mechanism approach
result results report reports priority critical unverified verified documented undocumented
""".split())

# Folder names every repository has; a file under api/ says nothing about who knows "the API".
_FOLDERS = {"api", "src", "web", "lib", "app", "test", "doc", "public", "component", "util", "github", "workflow",
            "server", "client", "packages", "package", "internal", "cmd", "main", "index"}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _stem(word: str) -> str:
    """payments → payment, policies → policy; leaves short words and "ss" endings alone."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _slug(name: str) -> str:
    return "-".join(_words(name))[:80] or "area"


# --- matching names to members ---------------------------------------------------


class People:
    """Matches the names different tools use to the project's members."""

    def __init__(self, users: list[User]) -> None:
        self.users = {u.id: u for u in users}
        self.by_full = {" ".join(_words(u.name)): u for u in users if u.name}
        firsts = Counter(_words(u.name)[0] for u in users if _words(u.name))
        self.by_first = {_words(u.name)[0]: u for u in users if _words(u.name) and firsts[_words(u.name)[0]] == 1}
        self.by_email = {u.email.split("@")[0].lower(): u for u in users if u.email}
        # Their names are not topics: "Domain dependency on Aarav" is about the domain. Names learnt
        # from the evidence ("Tanuj Keshattiwar" for the member "Tanuj") are added as they resolve.
        self.name_words = {w for u in users for w in _words(u.name)} | set(self.by_email)

    def resolve(self, raw: str | None) -> User | None:
        words = _words(raw or "")
        if not words:
            return None
        joined = " ".join(words)
        user = (self.by_full.get(joined) or self.by_email.get((raw or "").strip().lower())
                # "aarav-m" (a GitHub login), "Aarav" (chat), "Aarav M."
                or self.by_first.get(words[0]))
        if user is not None:
            self.name_words.update(words)
        return user


# --- results ------------------------------------------------------------------------


@dataclass
class Holder:
    user_id: uuid.UUID
    name: str
    share: float
    signals: dict[str, int] = field(default_factory=dict)


@dataclass
class Area:
    key: str
    name: str
    kind: str  # "system" or "contact"
    risk: str  # "high", "medium" or "low"
    top_share: float
    holders: list[Holder]
    backup: Holder | None
    importance: int
    summary: str
    subjects: list[str]
    claim_ids: list[uuid.UUID]
    signals: dict[str, int]
    leaving: bool = False
    capture_id: uuid.UUID | None = None
    capture_status: str = ""


@dataclass
class PersonLoad:
    user_id: uuid.UUID
    name: str
    high: int
    medium: int
    areas: list[str]
    leaving: bool


@dataclass
class Radar:
    run_id: uuid.UUID | None
    areas: list[Area]
    people: list[PersonLoad]
    withheld: int = 0
    grouping: bool = False  # the model is still grouping this run's claims into areas
    grouped_by: str = ""  # "model" or "words"


@dataclass
class Group:
    key: str
    name: str
    kind: str
    claims: list[Claim]


# --- grouping claims into areas: by shared words (no model) ---------------------------


def _subject(c: Claim) -> str:
    return (c.subject or c.statement[:80]).strip()


def _topics(subject: str, skip: set[str]) -> list[str]:
    return [_stem(w) for w in _words(subject) if len(w) > 2 and not w.isdigit() and not re.match(r"^[a-z]+\d+$", w)
            and w not in _GENERIC and _stem(w) not in _GENERIC and w not in skip]


def _label(key: str, claims: list[Claim]) -> str:
    """The word as people wrote it ("payments", "Firebase"), capitalised."""
    forms = Counter(w for c in claims for w in re.split(r"[^A-Za-z0-9]+", c.subject or "") if _stem(w.lower()) == key)
    # most used spelling; a tie goes to the longer, then the alphabetically first one (same answer every time)
    word = max(forms, key=lambda w: (forms[w], len(w), [-ord(ch) for ch in w])) if forms else key
    return word[:1].upper() + word[1:]


def group_by_words(claims: list[Claim], skip: set[str]) -> list[Group]:
    """Claims whose subjects share a topic word land in one area, named by the most shared word.
    Subjects with no word shared by another claim are left out: one claim isn't an area."""
    topics = {c.id: _topics(_subject(c), skip) for c in claims}
    df = Counter(t for ts in topics.values() for t in set(ts))
    by_key: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        shared = [t for t in topics[c.id] if df[t] >= 2]
        if shared:
            by_key[max(shared, key=lambda t: (df[t], len(t), t))].append(c)
    return [Group(key=k, name=_label(k, cs), kind="contact" if sum(c.type == ClaimType.contact for c in cs) * 2
                  > len(cs) else "system", claims=cs) for k, cs in by_key.items()]


# --- grouping claims into areas: by the model, once per run ----------------------------


class AreaOut(BaseModel):
    name: str
    kind: str = "system"
    subjects: list[str] = Field(default_factory=list, description="subject ids, e.g. S12")


class AreasOut(BaseModel):
    areas: list[AreaOut]


class Assigned(BaseModel):
    draft: str = Field(description="draft area id, e.g. A3")
    area: str = Field(description="the final area it belongs to")
    kind: str = "system"


class MergeOut(BaseModel):
    assignments: list[Assigned]


MAX_AREAS = 15  # more than this from the first pass and a second pass merges them


def _ids(refs: list[str], prefix: str, n: int) -> list[int]:
    """Positions from "S12", "12", or the whole line echoed back ("S12 | owner | ...")."""
    out = []
    for r in refs:
        m = re.match(rf"\s*{prefix}?(\d+)\b", r or "")
        if m and 0 < int(m.group(1)) <= n:
            out.append(int(m.group(1)) - 1)
    return out


def _named_from(name: str, subjects: list[str], per_subject: dict[str, list[Claim]]) -> bool:
    """A name must come from the area's own claims: a model can echo names it saw elsewhere
    ("Firebase" for subjects about load testing)."""
    said = {_stem(w) for s in subjects for c in per_subject[s] for w in _words(f"{s} {c.statement}")}
    named = {_stem(w) for w in _words(name) if len(w) > 2 and w not in ("and", "the")}
    return not named or bool(named & said)


def _area(name: str, kind: str, subjects: list[str]) -> dict:
    return {"key": _slug(name), "name": name, "kind": "contact" if kind.strip().lower() == "contact" else "system",
            "subjects": subjects}


def _current(db: Session, run: Run) -> list[Claim]:
    claims = list(db.scalars(select(Claim).where(Claim.run_id == run.id, Claim.status != ClaimStatus.rejected)))
    ids = {c.id for c in claims}
    return [c for c in claims if c.superseded_by not in ids]


def _fingerprint(subjects: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(subjects)).encode()).hexdigest()[:16]


def group_with_model(db: Session, project_id: uuid.UUID) -> dict:
    """Asks the model to group the latest run's claim subjects into areas, and stores the result on the run.
    Only subjects of claims whose label may go to the model are sent. Returns what was stored."""
    from app.agents import skills
    from app.agents.evidence import sendable_labels
    from app.llm import gateway

    run = latest_run(db, project_id)
    if run is None:
        return {}
    sendable = set(sendable_labels())
    claims = [c for c in _current(db, run) if c.sensitivity in sendable and _subject(c)]
    per_subject: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        per_subject[_subject(c)].append(c)
    subjects = sorted(per_subject, key=lambda s: (-len(per_subject[s]), s))[:MAX_SUBJECTS]
    stored: dict = {"fingerprint": _fingerprint(subjects), "subjects": len(subjects)}
    if not subjects:
        stored |= {"areas": []}
    else:
        skill = skills.load("radar_areas")
        lines = []
        for n, s in enumerate(subjects, start=1):
            example = max(per_subject[s], key=lambda c: c.impact)
            lines.append(f"S{n} | {example.type.value} | {guard.fence(s)[:120]} | "
                         f"{guard.fence(example.statement)[:160]}")
        try:
            out = gateway.generate(db, AreasOut, agent="radar_areas", version=skill.version, tier=skill.tier,
                                   system=skill.instructions, prompt="\n".join(lines), thinking=skill.thinking,
                                   attempts=2).value
            areas, taken = [], set()
            for a in out.areas:
                name = re.sub(r"\s+", " ", a.name).strip()[:60]
                picked = [subjects[i] for i in _ids(a.subjects, "S", len(subjects)) if subjects[i] not in taken]
                picked = list(dict.fromkeys(picked))
                if not (name and picked) or not _named_from(name, picked, per_subject):
                    log.info("radar: dropped area %r (no subjects, or its claims never mention it)", name)
                    continue
                if _slug(name) in {x["key"] for x in areas}:
                    continue
                taken.update(picked)
                areas.append(_area(name, a.kind, picked))
            if len(areas) > MAX_AREAS:  # a small model often makes an area per subject: merge them
                areas = _merge(db, areas, per_subject) or areas
            stored |= {"areas": areas}
        except Exception as e:  # noqa: BLE001 - any failure: the radar groups by words instead of waiting
            log.warning("radar: couldn't group areas with the model, grouping by words (%s)", e)
            db.rollback()
            run = db.get(Run, run.id)
            stored |= {"failed": str(e)[:200]}
    run.state = {**(run.state or {}), STATE_KEY: stored}
    db.commit()
    return stored


def _merge(db: Session, drafts: list[dict], per_subject: dict[str, list[Claim]]) -> list[dict]:
    """Second pass: the model merges too many small draft areas into the main parts. [] if it can't."""
    from app.agents import skills
    from app.llm import gateway

    skill = skills.load("radar_merge")
    lines = [f"A{n} | {guard.fence(d['name'])} | {guard.fence(', '.join(d['subjects'][:3]))[:200]}"
             for n, d in enumerate(drafts, start=1)]
    try:
        out = gateway.generate(db, MergeOut, agent="radar_merge", version=skill.version, tier=skill.tier,
                               system=skill.instructions, prompt="\n".join(lines), thinking=skill.thinking,
                               attempts=2).value
    except Exception as e:  # noqa: BLE001 - keep the first pass
        log.warning("radar: couldn't merge areas (%s)", e)
        return []
    # one line per draft says which final area it joins; drafts naming the same area are merged
    joined: dict[str, dict] = {}
    used: set[int] = set()
    for a in out.assignments:
        name = re.sub(r"\s+", " ", a.area).strip()[:60]
        ids = [i for i in _ids([a.draft], "A", len(drafts)) if i not in used]
        if not name or not ids:
            continue
        key = _slug(name)
        area = joined.setdefault(key, {"name": name, "kind": a.kind, "parts": []})
        area["parts"] += ids
        used.update(ids)
    merged = []
    for area in joined.values():
        subjects = [x for i in area["parts"] for x in drafts[i]["subjects"]]
        if _named_from(area["name"], subjects, per_subject):
            merged.append(_area(area["name"], area["kind"], subjects))
        else:  # a name its claims never use: keep its drafts as they were
            used.difference_update(area["parts"])
    # drafts the merge left out stay, if they are areas in their own right (several subjects)
    merged += [d for i, d in enumerate(drafts) if i not in used and len(d["subjects"]) >= 3]
    return merged


def _groups_from_model(stored: dict, claims: list[Claim]) -> list[Group]:
    """Puts the reader's claims into the stored areas. A claim written later (say, from a knowledge
    capture, whose subject is the area's name) joins the area its subject names."""
    by_subject = {s: a["key"] for a in stored.get("areas", []) for s in a["subjects"]}
    by_name = {a["name"].lower(): a["key"] for a in stored.get("areas", [])}
    meta = {a["key"]: a for a in stored.get("areas", [])}
    out: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        s = _subject(c)
        key = by_subject.get(s) or by_name.get(s.lower())
        if key:
            out[key].append(c)
    return [Group(key=k, name=meta[k]["name"], kind=meta[k]["kind"], claims=cs) for k, cs in out.items()]


# --- the radar --------------------------------------------------------------------------


def latest_run(db: Session, project_id: uuid.UUID) -> Run | None:
    return db.scalars(select(Run).where(Run.project_id == project_id, Run.kind == "reconstruct",
                                        Run.status == RunStatus.done).order_by(Run.created_at.desc())).first()


def needs_grouping(run: Run | None) -> bool:
    """A model is configured and this run hasn't been grouped (or tried) yet."""
    return run is not None and llm.configured() and STATE_KEY not in (run.state or {})


def _members(db: Session, project_id: uuid.UUID) -> list[User]:
    return list(db.scalars(select(User).join(Membership, Membership.user_id == User.id)
                           .where(Membership.project_id == project_id).distinct()))


def _leaving(db: Session, project_id: uuid.UUID) -> set[uuid.UUID]:
    """People who are the leaver on a handover that isn't finished."""
    return set(db.scalars(select(Handover.leaver_id).where(
        Handover.project_id == project_id, Handover.kind != CAPTURE_KIND,
        Handover.status != HandoverStatus.acknowledged)))


def _captures(db: Session, project_id: uuid.UUID) -> dict[tuple[str, uuid.UUID], Handover]:
    rows = db.scalars(select(Handover).where(Handover.project_id == project_id, Handover.kind == CAPTURE_KIND)
                      .order_by(Handover.created_at))
    return {((h.scope or {}).get("area", ""), h.leaver_id): h for h in rows}


def compute(db: Session, project_id: uuid.UUID, p: Principal) -> Radar:
    run = latest_run(db, project_id)
    if run is None:
        return Radar(run_id=None, areas=[], people=[])
    if needs_grouping(run):
        return Radar(run_id=run.id, areas=[], people=[], grouping=True)
    visible, withheld = gatekeeper.ClaimFilter(db, p, project_id).split(_current(db, run))

    users = _members(db, project_id)
    people = People(users)
    for c in visible:  # learn every spelling of a member's name before reading subjects
        people.resolve(c.owner_name)
    stored = (run.state or {}).get(STATE_KEY) or {}
    if stored.get("areas"):
        groups, grouped_by = _groups_from_model(stored, visible), "model"
    else:
        groups, grouped_by = group_by_words(visible, people.name_words), "words"

    # Everything the visible claims cite, plus the commits (for the code signal), in one go.
    cites = db.execute(select(ClaimEvidence.claim_id, EvidenceUnit)
                       .join(EvidenceUnit, EvidenceUnit.id == ClaimEvidence.evidence_id)
                       .where(ClaimEvidence.claim_id.in_([c.id for c in visible]))).all() if visible else []
    by_claim: dict[uuid.UUID, list[EvidenceUnit]] = defaultdict(list)
    for claim_id, unit in cites:
        by_claim[claim_id].append(unit)
    commits = db.scalars(select(EvidenceUnit).join(Source, Source.id == EvidenceUnit.source_id).where(
        EvidenceUnit.project_id == project_id, EvidenceUnit.kind == "commit",
        gatekeeper.visible_evidence_clause(p))).all()
    commit_paths = [(u, {_stem(w) for f in (u.meta or {}).get("files") or [] for w in _words(f)}) for u in commits]

    leaving = _leaving(db, project_id)
    captures = _captures(db, project_id)
    out: list[Area] = []
    for g in groups:
        counts: dict[uuid.UUID, Counter] = defaultdict(Counter)

        def add(user: User | None, signal: str, counts=counts) -> None:
            if user is not None:
                counts[user.id][signal] += 1

        seen: set[uuid.UUID] = set()
        for c in g.claims:
            if c.type in OWNERSHIP_TYPES:
                add(people.resolve(c.owner_name), "ownership")
            for u in by_claim.get(c.id, []):
                if u.id in seen:
                    continue
                seen.add(u.id)
                if u.kind in TICKET_KINDS:
                    for name in (u.meta or {}).get("assignees") or []:
                        add(people.resolve(name), "tickets")
                if u.kind in TALK_KINDS or u.kind in TICKET_KINDS:
                    add(people.resolve(u.author), "talk")
        # commits that touched files named after the area ("payments/poll.ts" for "Payments")
        topic_words = {_stem(w) for w in _words(g.name)} - _GENERIC - _FOLDERS
        topic_words = {w for w in topic_words if len(w) > 2}
        if topic_words:
            for u, words in commit_paths:
                if topic_words & words:
                    add(people.resolve(u.author), "code")

        weight = {uid: sum(WEIGHTS[s] * n for s, n in sig.items()) for uid, sig in counts.items()}
        total = sum(weight.values())
        if total < MIN_WEIGHT:
            continue
        holders = sorted((Holder(user_id=uid, name=people.users[uid].name, share=w / total, signals=dict(counts[uid]))
                          for uid, w in weight.items()), key=lambda h: -h.share)
        top = holders[0]
        backup = next((h for h in holders[1:] if h.share >= BACKUP_SHARE), None)
        if top.share >= HIGH_SHARE and backup is None:
            risk = "high"
        elif top.share >= MEDIUM_SHARE and (backup is None or top.share >= HIGH_SHARE):
            risk = "medium"
        else:
            risk = "low"
        signals = Counter()
        for sig in counts.values():
            signals.update(sig)
        importance = sum(c.impact for c in g.claims) + 2 * sum(
            1 for c in g.claims if c.type in (ClaimType.risk, ClaimType.blocker))
        pct = round(100 * top.share)
        summary = (f"{pct}% {top.name.split()[0]}, no backup owner" if backup is None
                   else f"{pct}% {top.name.split()[0]}, backup {backup.name.split()[0]} ({round(100 * backup.share)}%)")
        capture = captures.get((g.key, top.user_id))
        out.append(Area(
            key=g.key, name=g.name, kind=g.kind, risk=risk, top_share=top.share,
            holders=holders, backup=backup, importance=importance, summary=summary,
            subjects=[s for s, _ in Counter(c.subject for c in g.claims if c.subject).most_common(4)],
            claim_ids=[c.id for c in g.claims], signals=dict(signals), leaving=top.user_id in leaving,
            capture_id=capture.id if capture else None, capture_status=capture.status.value if capture else "",
        ))

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda a: (order[a.risk], not a.leaving, -a.importance, -a.top_share, a.name))

    load: dict[uuid.UUID, PersonLoad] = {}
    for a in out:
        if a.risk == "low":
            continue
        top = a.holders[0]
        pl = load.setdefault(top.user_id, PersonLoad(user_id=top.user_id, name=top.name, high=0, medium=0,
                                                       areas=[], leaving=top.user_id in leaving))
        pl.high += a.risk == "high"
        pl.medium += a.risk == "medium"
        pl.areas.append(a.name)
    ranked = sorted(load.values(), key=lambda x: (-x.high, -x.medium, x.name))
    return Radar(run_id=run.id, areas=out, people=ranked, withheld=sum(withheld.values()), grouped_by=grouped_by)


def area(db: Session, project_id: uuid.UUID, p: Principal, key: str) -> Area | None:
    return next((a for a in compute(db, project_id, p).areas if a.key == key), None)
