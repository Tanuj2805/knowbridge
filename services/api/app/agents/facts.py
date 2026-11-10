"""Claims read straight from structured data, with no model involved: who made
most of the commits to a folder, CI that keeps failing, pull requests nobody
has touched in weeks, tasks past their due date.

They go through the same `save_claim` check as model claims (the quote must be
in the cited item), and are marked as coming from system data so the Skeptic
can grade them Verified.
"""

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import retrieval
from app.agents.base import AgentContext, Cite, DraftClaim, save_claim
from app.agents.evidence import local_date
from app.db.models import ClaimType, EvidenceUnit, Membership, User

SYSTEM_DATA = "system data"
OWNER_MIN_COMMITS = 5
OWNER_MIN_SHARE = 0.5
STALE_AFTER = timedelta(days=14)
DONE_STATUSES = {"done", "closed", "resolved", "complete", "completed", "shipped", "released", "cancelled"}


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _day(d: datetime) -> str:
    day = local_date(d)
    return f"{day.day} {day:%b %Y}"


def _iso(d: datetime | None) -> str:
    return local_date(d).isoformat() if d else ""


def _people(db: Session, ctx: AgentContext) -> list[str]:
    return list(db.scalars(select(User.name).join(Membership, Membership.user_id == User.id)
                           .where(Membership.project_id == ctx.project_id)))


def person(handle: str, names: list[str]) -> str:
    """'sneha-k' or 'Sneha' -> 'Sneha Kulkarni' when exactly one member matches."""
    if not handle or handle in names:
        return handle
    token = re.split(r"[-_.\s]", handle.strip().lower())[0]
    matches = [n for n in names if n.split()[0].lower() == token]
    return matches[0] if len(matches) == 1 else handle


def _first_line(u: EvidenceUnit) -> str:
    return u.text.strip().splitlines()[0] if u.text.strip() else u.title


def _save(db: Session, ctx: AgentContext, agent: str, allowed: set[ClaimType], source: str, units: list[EvidenceUnit],
          quotes: list[str], **fields) -> bool:
    ids = {f"E{n}": u for n, u in enumerate(units, start=1)}
    draft = DraftClaim(evidence=[Cite(id=f"E{n}", quote=q) for n, q in enumerate(quotes, start=1)], **fields)
    claim = save_claim(db, ctx, agent, draft, ids, allowed)
    if claim is None:
        return False
    claim.grade_reason = f"{SYSTEM_DATA}: {source}"
    return True


def _units(db: Session, ctx: AgentContext, *kinds: str) -> list[EvidenceUnit]:
    q = retrieval.visible_units(ctx.principal, ctx.project_id, retrieval.Filters()).where(
        EvidenceUnit.kind.in_(kinds))
    return list(db.scalars(q))


def as_of(db: Session, ctx: AgentContext) -> datetime:
    """'Now' for this project: the newest evidence, so old exports are judged fairly."""
    latest = db.scalar(select(func.max(EvidenceUnit.occurred_at)).where(EvidenceUnit.project_id == ctx.project_id))
    return latest or datetime.now(UTC)


def ownership(db: Session, ctx: AgentContext, agent: str) -> int:
    """Owner claims from git history (live GitHub sources)."""
    names = _people(db, ctx)
    allowed = {ClaimType.owner}
    saved = 0
    for u in _units(db, ctx, "code_ownership"):
        authors: dict[str, int] = (u.meta or {}).get("authors") or {}
        total = sum(authors.values())
        if total < OWNER_MIN_COMMITS:
            continue
        top, n = max(authors.items(), key=lambda kv: kv[1])
        if n / total < OWNER_MIN_SHARE:
            continue
        module = (u.meta or {}).get("module", u.title)
        if module.startswith("("):  # "(top level)": config files at the root, not a module anyone owns
            continue
        who = person(top, names)
        saved += _save(
            db, ctx, agent, allowed, "git history", [u], [f"{top}: {n}"],
            type="owner", subject=module[:300], owner=who, impact=2,
            when=_iso(u.occurred_at),
            statement=f"{who} made {round(100 * n / total)}% of the commits to {module} ({n} of {total}).",
        )
    return saved


def risks(db: Session, ctx: AgentContext, agent: str) -> int:
    """Blockers and risks from CI runs, pull requests and task cards."""
    names = _people(db, ctx)
    now = as_of(db, ctx)
    allowed = {ClaimType.blocker, ClaimType.risk}
    saved = 0

    # CI that is failing now: the run of failures since the last success.
    runs: dict[tuple[str, str], list[EvidenceUnit]] = defaultdict(list)
    for u in _units(db, ctx, "check"):
        if u.occurred_at:
            runs[(u.title, (u.meta or {}).get("branch") or "")].append(u)
    for (title, branch), seq in runs.items():
        seq.sort(key=lambda u: u.occurred_at)
        failing = []
        for u in reversed(seq):
            if (u.meta or {}).get("conclusion") not in ("failure", "timed_out"):
                break
            failing.append(u)
        if not failing:
            continue
        first, last = failing[-1], failing[0]
        workflow = title.removeprefix("CI: ")
        cited = [first] if first is last else [first, last]
        saved += _save(
            db, ctx, agent, allowed, "CI runs", cited, [_first_line(u).split(" (commit")[0] for u in cited],
            type="blocker", subject=f"CI {workflow}"[:300], when=_iso(first.occurred_at), impact=2,
            statement=(f"CI workflow “{workflow}”{f' on {branch}' if branch else ''} has failed since "
                       f"{_day(first.occurred_at)} ({len(failing)} run{'s' if len(failing) > 1 else ''} in a row)."),
        )

    # Open pull requests with no activity for weeks.
    activity: dict[str, datetime] = {}
    for c in _units(db, ctx, "pr_comment", "pr_review"):
        pr = str((c.meta or {}).get("pr") or "")
        if pr and c.occurred_at:
            activity[pr] = max(activity.get(pr, c.occurred_at), c.occurred_at)
    for u in _units(db, ctx, "pull_request"):
        meta = u.meta or {}
        if meta.get("state") != "open":
            continue
        num = u.locator.removeprefix("PR #")
        last = max(d for d in (u.occurred_at, _when(meta.get("updated_at")), activity.get(num)) if d)
        if now - last < STALE_AFTER:
            continue
        who = person(u.author, names)
        title = u.title.split(": ", 1)[-1]
        saved += _save(
            db, ctx, agent, allowed, "pull requests", [u], [_first_line(u)],
            type="blocker", subject=title[:300], owner=who, when=_iso(last), impact=2,
            statement=f"PR #{num} “{title}” by {who} is still open with no activity since {_day(last)}.",
        )

    # Task cards past their due date and still open.
    for u in _units(db, ctx, "card"):
        meta = u.meta or {}
        due = _when(meta.get("due"))
        status = str(meta.get("status") or "").strip().lower()
        if not due or meta.get("closed") or status in DONE_STATUSES or local_date(due) >= local_date(now):
            continue
        assignees = [person(a, names) for a in meta.get("assignees") or []]
        saved += _save(
            db, ctx, agent, allowed, "task board", [u], [u.title],
            type="risk", subject=u.title[:300], owner=", ".join(assignees), due=_iso(due), impact=2,
            when=_iso(u.occurred_at or now),
            statement=(f"“{u.title}” was due {_day(due)} and is still open"
                       f"{' (' + ', '.join(assignees) + ')' if assignees else ', with nobody assigned'}."),
        )
    return saved
