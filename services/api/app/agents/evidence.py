"""What agents read: evidence packets, rendered as data, with short ids to cite.

Only evidence the run's owner may see, and whose label may go to the model
(LLM_EXTERNAL_MAX_LABEL), is ever packed. Agents cite items by packet-local ids
(E1, E2…) and must quote them word for word; `find_quote` enforces that.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import guard, retrieval
from app.config import get_settings
from app.db.models import EvidenceUnit, Membership, Project, Sensitivity, Source, User
from app.gatekeeper.policy import Principal

MAX_PACKET_CHARS = 10_000
MAX_UNIT_CHARS = 3_000
_LABELS = ["team", "restricted", "confidential"]


def sendable_labels() -> list[Sensitivity]:
    cap = get_settings().llm_external_max_label
    return [Sensitivity(x) for x in _LABELS[: _LABELS.index(cap) + 1]]


@dataclass
class Packet:
    key: str
    kind: str  # thread, chat_day, document, meeting, commits, repo_file, ci, ownership, cards, single
    title: str
    units: list[EvidenceUnit] = field(default_factory=list)

    @property
    def size(self) -> int:
        """Characters agents will read (what bundles are filled by)."""
        return sum(len(u.title) + len(for_agents(u)) for u in self.units)


def _packet_key(u: EvidenceUnit) -> tuple[str, str]:
    group = retrieval.group_key(u)
    if group[0] in ("jira", "pr", "issue", "trello"):
        return "thread", f"{group[0]}:{group[1]}"
    if group[0] == "meeting":
        return "meeting", group[1]
    m = u.meta or {}
    day = local_date(u.occurred_at or datetime.now(UTC))
    if u.kind == "message":
        return "chat_day", f"{u.source_id}:{m.get('channel') or m.get('chat') or u.title}:{day}"
    if u.kind == "doc_section":
        return "document", f"{u.source_id}:{m.get('file')}"
    if u.kind == "file":
        return "repo_file", f"{u.source_id}:{m.get('path')}"
    if u.kind == "commit":
        year, week, _ = day.isocalendar()
        return "commits", f"{u.source_id}:{year}-W{week:02d}"
    if u.kind == "check":
        return "ci", str(u.source_id)
    if u.kind == "code_ownership":
        return "ownership", str(u.source_id)
    if u.kind == "card":
        return "cards", str(u.source_id)
    return "single", str(u.id)


def packet_units(db: Session, p: Principal, project_id: uuid.UUID) -> list[EvidenceUnit]:
    q = retrieval.visible_units(p, project_id, retrieval.Filters()).where(
        EvidenceUnit.sensitivity.in_(sendable_labels())
    )
    return list(db.scalars(q))


def build_packets(units: list[EvidenceUnit], source_names: dict[uuid.UUID, str]) -> list[Packet]:
    groups: dict[str, Packet] = {}
    for u in sorted(units, key=lambda u: (u.occurred_at or datetime.min.replace(tzinfo=UTC), u.locator)):
        kind, key = _packet_key(u)
        pk = groups.get(key)
        if pk is None:
            pk = groups[key] = Packet(key=key, kind=kind, title=_title(kind, u, source_names))
        pk.units.append(u)
    out: list[Packet] = []
    for pk in groups.values():
        if pk.size <= MAX_PACKET_CHARS:
            out.append(pk)
            continue
        part, size, n = [], 0, 1
        for u in pk.units:
            if part and size + len(u.text) > MAX_PACKET_CHARS:
                out.append(Packet(f"{pk.key}#{n}", pk.kind, f"{pk.title} (part {n})", part))
                part, size, n = [], 0, n + 1
            part.append(u)
            size += len(u.title) + len(u.text)
        out.append(Packet(f"{pk.key}#{n}", pk.kind, f"{pk.title} (part {n})" if n > 1 else pk.title, part))
    return out


def _title(kind: str, u: EvidenceUnit, source_names: dict[uuid.UUID, str]) -> str:
    src = source_names.get(u.source_id, "source")
    m = u.meta or {}
    if kind == "thread":
        return f"{src}: {(u.title or u.locator).removeprefix('Comment on ')[:100]}"
    if kind == "chat_day":
        return f"{src}, {local_date(u.occurred_at) if u.occurred_at else ''}"
    if kind == "document":
        return f"{src}: {m.get('file', u.title)}"
    if kind == "meeting":
        return f"Meeting: {m.get('meeting', u.title)}"
    if kind == "commits":
        return f"{src}: commits, week of {local_date(u.occurred_at) if u.occurred_at else ''}"
    return f"{src}: {u.title[:100]}"


JIRA_RECENT_CHANGES = 5
_ASSIGNEE_CHANGE = re.compile(r":\s+assignee\s", re.I)


def for_agents(u: EvidenceUnit) -> str:
    """The item's text as agents read it. A Jira ticket's change history is ~40% of its
    text; agents get every change of assignee (who held it) plus the latest few moves.
    Quotes are still checked against the full stored text."""
    if (u.meta or {}).get("provider") != "jira" or "\nHistory:\n" not in u.text:
        return u.text
    head, _, rest = u.text.partition("\nHistory:\n")
    lines = rest.split("\n")
    n = 0
    while n < len(lines) and lines[n].startswith("  "):
        n += 1
    history, after = [ln for ln in lines[:n] if not ln.strip().startswith("…")], lines[n:]
    recent = set(range(max(0, len(history) - JIRA_RECENT_CHANGES), len(history)))
    kept = [ln for i, ln in enumerate(history) if i in recent or _ASSIGNEE_CHANGE.search(ln)]
    earlier = len(history) - len(kept)
    note = [f"  … {earlier} other change{'' if earlier == 1 else 's'} not shown"] if earlier else []
    return "\n".join([head, "History:", *note, *kept, *after])


def render(packet: Packet, source_names: dict[uuid.UUID, str], start: int = 1) -> tuple[str, dict[str, EvidenceUnit]]:
    """The packet as <evidence> blocks; returns the text and {"E1": unit, …}."""
    ids: dict[str, EvidenceUnit] = {}
    blocks = []
    for n, u in enumerate(packet.units, start=start):
        eid = f"E{n}"
        ids[eid] = u
        attrs = {
            "id": eid,
            "source": source_names.get(u.source_id, ""),
            "kind": u.kind,
            "author": u.author,
            "date": local_date(u.occurred_at).isoformat() if u.occurred_at else "",
            "where": u.locator,
        }
        head = " ".join(f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items() if v)
        text = guard.fence(for_agents(u))  # a source can't close the tag or pose as an id
        body = text if len(text) <= MAX_UNIT_CHARS else text[:MAX_UNIT_CHARS] + " …"
        title = f"{guard.fence(u.title)}\n" if u.title and u.title not in body[:200] else ""
        blocks.append(f"<evidence {head}>\n{title}{body}\n</evidence>")
    return "\n\n".join(blocks), ids


def local_date(dt: datetime) -> date:
    """The calendar date where the team is, not in UTC (01:20 IST on 20 Oct is 20 Oct)."""
    return dt.astimezone(ZoneInfo(get_settings().timezone)).date()


_SPACE = re.compile(r"\s+")
# Models quote what they read, not the Markdown around it: "**PWA only.**" is quoted as "PWA only."
_FANCY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "…": "...", "*": None, "`": None})


def _norm(s: str) -> str:
    return _SPACE.sub(" ", s.translate(_FANCY)).strip().lower()


def find_quote(unit: EvidenceUnit, quote: str) -> bool:
    """True when `quote` really appears in the item (whitespace, case, curly
    quotes and Markdown emphasis aside). Anything else is treated as invented and dropped."""
    q = _norm(quote).strip(" .\"'")
    if len(q) < 6:
        return False
    hay = f"{unit.title}\n{unit.text}"
    return q in _norm(hay) or q in _norm(guard.fence(hay))  # agents read the fenced text


def project_brief(db: Session, project_id: uuid.UUID) -> str:
    """A short, fixed context every agent gets: what the project is and who is on it."""
    project = db.get(Project, project_id)
    people = db.execute(
        select(User.name, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.project_id == project_id)
    ).all()
    roles: dict[str, list[str]] = {}
    for name, role in people:
        roles.setdefault(name, []).append(role.value)
    sources = db.scalars(select(Source.name).where(Source.project_id == project_id)).all()
    # The newest evidence date, not today's: the brief (and so the answer cache)
    # only changes when the evidence does.
    latest = db.scalar(select(func.max(EvidenceUnit.occurred_at)).where(EvidenceUnit.project_id == project_id))
    lines = [
        f"Project: {project.name}",
        f"About: {project.description or '(no description)'}",
        f"Evidence up to: {local_date(latest).isoformat() if latest else 'unknown'}",
        "People on the project: " + "; ".join(f"{n} ({', '.join(r)})" for n, r in sorted(roles.items())),
        "Sources: " + ", ".join(sources),
        "The same person may appear under a handle (e.g. aarav-m) or a first name (Aarav).",
    ]
    return "\n".join(lines)
