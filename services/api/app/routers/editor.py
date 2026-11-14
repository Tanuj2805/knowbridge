"""KnowBridge in the editor: personal access tokens, and what the VS Code extension and the MCP
server read.

  - /me/tokens: make, list and revoke your tokens (from the website only; a token can't make tokens)
  - /token: who a token belongs to and which project it opens
  - /projects/resolve?repo=owner/name: the project a git repository belongs to
  - /projects/{id}/code-context?path=...: owners, decisions, risks and claims for a file or folder
  - /projects/{id}/claims/{claim_id}: one claim with its quotes and sources

Everything a token reaches goes through the same checks as the website: a claim is shown only if
the reader may see every item it cites, and successors see approved claims only.
"""

import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import audit, gatekeeper, radar, rag
from app.auth import DB, CurrentUser, ProjectPrincipal, new_token, token_of
from app.config import get_settings
from app.db.models import (
    ApiToken,
    Claim,
    ClaimStatus,
    EvidenceUnit,
    Membership,
    Project,
    Source,
    SourceKind,
    User,
)
from app.gatekeeper import policy

router = APIRouter(tags=["editor"])

CODE_KINDS = ("file", "commit", "pr_comment", "code_ownership")
GENERIC_STEMS = {"index", "utils", "util", "types", "type", "config", "configs", "layout", "route", "routes",
                 "main", "styles", "style", "helpers", "helper", "constants", "schema", "schemas", "model",
                 "models", "tests", "setup", "server", "client", "common", "shared", "readme", "package",
                 "global", "globals", "public", "assets", "components", "component", "hooks", "services",
                 "service", "error", "errors", "loading", "template", "views", "pages", "app", "src", "lib"}
TYPE_ORDER = ["owner", "decision", "risk", "blocker", "dependency", "recurring_problem", "open_question",
              "next_action", "contact"]


# --- tokens --------------------------------------------------------------------------------


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    project_id: uuid.UUID


class TokenOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    project_id: uuid.UUID
    project_name: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool


class NewTokenOut(TokenOut):
    token: str  # shown once


def _token_out(t: ApiToken, project_name: str) -> TokenOut:
    return TokenOut(id=t.id, name=t.name, prefix=t.prefix, project_id=t.project_id, project_name=project_name,
                    created_at=t.created_at, expires_at=t.expires_at, last_used_at=t.last_used_at,
                    revoked=t.revoked_at is not None)


def _website_only(request: Request) -> None:
    if token_of(request) is not None:
        raise HTTPException(403, "Access tokens can't manage tokens. Use the KnowBridge website.")


@router.post("/me/tokens", response_model=NewTokenOut, status_code=201)
def create_token(body: TokenIn, request: Request, user: CurrentUser, db: DB):
    _website_only(request)
    project = db.get(Project, body.project_id)
    if project is None or not gatekeeper.principal(db, body.project_id, user.id).is_member:
        raise HTTPException(404, "Project not found.")
    raw, digest, prefix = new_token()
    t = ApiToken(user_id=user.id, project_id=project.id, name=body.name.strip(), token_hash=digest, prefix=prefix,
                 expires_at=datetime.now(UTC) + timedelta(days=get_settings().token_days))
    db.add(t)
    db.flush()
    audit.record(db, actor_id=user.id, action="token.create", object_type="token", object_id=t.id,
                 project_id=project.id, name=t.name)
    db.commit()
    db.refresh(t)
    return NewTokenOut(**_token_out(t, project.name).model_dump(), token=raw)


@router.get("/me/tokens", response_model=list[TokenOut])
def list_tokens(request: Request, user: CurrentUser, db: DB):
    _website_only(request)
    rows = db.execute(select(ApiToken, Project.name).join(Project, Project.id == ApiToken.project_id)
                      .where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())).all()
    return [_token_out(t, name) for t, name in rows]


@router.delete("/me/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, request: Request, user: CurrentUser, db: DB) -> None:
    _website_only(request)
    t = db.get(ApiToken, token_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Token not found.")
    if t.revoked_at is None:
        t.revoked_at = datetime.now(UTC)
        audit.record(db, actor_id=user.id, action="token.revoke", object_type="token", object_id=t.id,
                     project_id=t.project_id, name=t.name)
        db.commit()


@router.get("/token")
def whoami(request: Request, user: CurrentUser, db: DB) -> dict:
    """For the extension and MCP server: whose token this is and which project it opens."""
    t = token_of(request)
    if t is None:
        raise HTTPException(400, "Call this with an access token.")
    project = db.get(Project, t.project_id)
    p = gatekeeper.principal(db, t.project_id, user.id)
    if project is None or not p.is_member:
        raise HTTPException(404, "You're no longer a member of this token's project.")
    return {"user": {"name": user.name, "email": user.email}, "project": {"id": str(project.id), "name": project.name},
            "roles": sorted(r.value for r in p.roles), "approved_only": not policy.can_view_ledger(p),
            "web_url": get_settings().web_url.rstrip("/")}


# --- which project a repository belongs to ---------------------------------------------------


def _repo_key(text: str) -> str:
    """"https://github.com/Owner/Repo.git", "git@github.com:Owner/Repo" and "Owner/Repo" all → "owner/repo"."""
    t = text.strip().lower().removesuffix("/").removesuffix(".git")
    m = re.search(r"([\w.-]+)/([\w.-]+)$", t)
    return f"{m.group(1)}/{m.group(2)}" if m else t


@router.get("/projects/resolve")
def resolve_project(request: Request, user: CurrentUser, db: DB, repo: str = Query(min_length=3, max_length=300)):
    """Projects of yours with a GitHub source for this repository (a token sees only its own project)."""
    key = _repo_key(repo)
    member_of = select(Membership.project_id).where(Membership.user_id == user.id)
    q = select(Source, Project).join(Project, Project.id == Source.project_id).where(
        Source.kind == SourceKind.github, Source.project_id.in_(member_of))
    t = token_of(request)
    if t is not None:
        q = q.where(Source.project_id == t.project_id)
    found: dict[uuid.UUID, Project] = {}
    for source, project in db.execute(q).all():
        names = [str((source.config or {}).get("repo", "")), source.name]
        if any(n and _repo_key(n) == key for n in names):
            found[project.id] = project
    return {"repo": key, "projects": [{"id": str(p.id), "name": p.name} for p in found.values()]}


# --- what the project knows about a file or folder --------------------------------------------


class CodeSource(BaseModel):
    kind: str
    title: str
    permalink: str
    source_name: str
    occurred_at: datetime | None


class CodeClaim(BaseModel):
    id: uuid.UUID
    type: str
    grade: str
    status: str
    statement: str
    subject: str
    owner_name: str
    why: str  # how it is tied to this path
    sources: list[CodeSource]
    url: str | None


class CodeOwner(BaseModel):
    name: str
    commits: int
    share: float
    last_change: datetime | None


class CodeContext(BaseModel):
    path: str
    folder: bool
    found: bool  # anything at all is recorded about this path
    owners: list[CodeOwner]
    commits: int
    last_change: datetime | None
    claims: list[CodeClaim]
    counts: dict[str, int]
    withheld: int
    approved_only: bool
    project_url: str
    repo_commits: int  # commits the reader may see in the whole project (0: no repository connected)
    created_by: str  # author of the earliest commit we have that touched it ("" if unknown)
    created_at: datetime | None


def _norm_path(path: str) -> str:
    p = path.replace("\\", "/").strip()
    p = re.sub(r"^(\./)+", "", p).lstrip("/")
    return re.sub(r"/{2,}", "/", p)


def _same_file(f: str, path: str) -> bool:
    """The repository's path and the editor's path name the same file. The editor's path can carry
    extra leading folders (a parent folder opened in the editor: "backend/app/routes/x.py" for the
    repository's "app/routes/x.py"), or be shorter (a sub-folder opened as the workspace)."""
    if f == path or path.endswith("/" + f):
        return True
    return path.count("/") >= 1 and f.endswith("/" + path)


def _under(f: str, folder: str) -> bool:
    """A repository path lies in the editor's folder, allowing the same extra leading folders."""
    if f.startswith(folder):
        return True
    parts = folder.rstrip("/").split("/")
    # drop leading folders the repository doesn't have, keeping at least two levels ("app/routes/")
    return any(f.startswith("/".join(parts[i:]) + "/") for i in range(1, max(1, len(parts) - 1)))


NEAR_CHARS = 400  # a claim's quote this close to a mention of the file is about that file
_FILE_NAME = re.compile(r"(?<![\w.-])[\w.-]+\.(?:py|ts|tsx|js|jsx|mjs|go|java|rb|rs|cs|php|kt|swift|sql|ya?ml|json|"
                        r"toml|sh|css|scss|html|vue|svelte|c|h|cpp|md)(?![\w-])", re.I)


def _names_other_file(statement: str, base: str) -> bool:
    """The claim is about some other named file (and not this one)."""
    names = {m.group(0).lower() for m in _FILE_NAME.finditer(statement)}
    return bool(names) and base.lower() not in names


def _quoted_near(quote: str, text: str, mention: re.Pattern) -> bool:
    """The passage a claim rests on mentions the file, or sits close to a mention of it in its source
    (tickets often list the files first and explain them in the next lines)."""
    if mention.search(quote):
        return True
    at = text.find(quote[:60]) if quote else -1
    return at >= 0 and any(abs(at - m.start()) <= NEAR_CHARS for m in mention.finditer(text))


def _touches(files: list[str], path: str, folder: bool) -> bool:
    files = [_norm_path(f) for f in files or []]
    return any(_under(f, path) for f in files) if folder else any(_same_file(f, path) for f in files)


@router.get("/projects/{project_id}/code-context", response_model=CodeContext)
def code_context(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB,
                 path: str = Query(min_length=1, max_length=500)):
    """Owners, decisions, risks and claims for a file (or a folder, when the path ends in "/")."""
    ctx = file_context(db, p, project_id, path)
    audit.record(db, actor_id=user.id, action="editor.context", object_type="project", object_id=project_id,
                 project_id=project_id, path=ctx.path[:200], claims=len(ctx.claims))
    db.commit()
    return ctx


def file_context(db, p, project_id: uuid.UUID, path: str) -> CodeContext:
    """What the project records about one path, for this reader (no audit; callers record their use)."""
    folder = path.strip().endswith("/") or path.strip() in ("", ".")
    path = _norm_path(path)
    if folder and path and not path.endswith("/"):
        path += "/"
    approved_only = not policy.can_view_ledger(p)
    web = get_settings().web_url.rstrip("/")

    # 1. Code evidence for this path that the reader may see: the file itself, commits and review
    #    comments that touched it, and the ownership summary of its folder.
    units = db.scalars(select(EvidenceUnit).join(Source, Source.id == EvidenceUnit.source_id).where(
        EvidenceUnit.project_id == project_id, EvidenceUnit.kind.in_(CODE_KINDS),
        gatekeeper.visible_evidence_clause(p))).all()
    hits: list[EvidenceUnit] = []
    commits: list[EvidenceUnit] = []
    for u in units:
        meta = u.meta or {}
        if u.kind == "commit" and _touches(meta.get("files") or [], path, folder):
            commits.append(u)
            hits.append(u)
        elif u.kind in ("file", "pr_comment") and meta.get("path") and _touches([meta["path"]], path, folder):
            hits.append(u)
        elif u.kind == "code_ownership" and meta.get("module") and meta["module"] != "(top level)" and (
                ("/" + path).find("/" + meta["module"]) >= 0 or (folder and _under(meta["module"], path))):
            hits.append(u)
    repo_commits = sum(1 for u in units if u.kind == "commit")

    # 2. Who changed it, from those commits (names matched to members, bots left out).
    people = radar.People(list(db.scalars(select(User).join(Membership, Membership.user_id == User.id)
                                          .where(Membership.project_id == project_id).distinct())))
    by_person: Counter = Counter()
    last: dict[str, datetime] = {}
    for c in commits:
        member = people.resolve(c.author)
        name = member.name if member else ""
        if not name:
            continue
        by_person[name] += 1
        if c.occurred_at and (name not in last or c.occurred_at > last[name]):
            last[name] = c.occurred_at
    total = sum(by_person.values())
    first = min((c for c in commits if c.occurred_at), key=lambda c: c.occurred_at, default=None)
    first_member = people.resolve(first.author) if first else None
    created_by = first_member.name if first_member else (first.author if first else "")
    owners = [CodeOwner(name=n, commits=k, share=k / total, last_change=last.get(n)) for n, k in
              by_person.most_common(6)]

    # 3. Claims: the ones citing that evidence, and the ones that name the file or folder.
    visible, cites = rag.visible_claims(db, p, project_id)
    all_current, _ = _current_claims(db, project_id)
    hit_ids = {u.id for u in hits}
    base = path.rstrip("/").rsplit("/", 1)[-1]
    mention = re.compile(rf"(?<![\w.-]){re.escape(base)}(?![\w-])", re.I) if len(base) >= 4 else None
    # The file's topic: "payments" for payments.ts, "checkin" for a checkin/ folder. Generic names
    # (index, utils, page...) say nothing, so they're skipped.
    stem = re.sub(r"\.[\w]+$", "", base).lower()
    stem = re.sub(r"(ies|s)$", lambda m: "y" if m.group(1) == "ies" else "", stem) if len(stem) > 5 else stem
    topic = (re.compile(rf"\b{re.escape(stem)}(s|es)?\b", re.I)
             if len(stem) >= 5 and stem not in GENERIC_STEMS and re.fullmatch(r"[a-z][a-z0-9_-]+", stem) else None)
    shown: list[CodeClaim] = []
    for c in visible:
        if approved_only and c.status not in (ClaimStatus.approved, ClaimStatus.edited):
            continue
        cited = [(ce, u, s) for ce, u, s in cites.get(c.id, [])]
        why = ""
        if any(u.id in hit_ids for _, u, _ in cited):
            kinds = {u.kind for _, u, _ in cited if u.id in hit_ids}
            why = ("cites a commit that changed it" if "commit" in kinds else
                   "cites its review comments" if "pr_comment" in kinds else
                   "cites the file" if "file" in kinds else "cites who changed this folder")
        elif mention and (mention.search(c.statement) or mention.search(c.subject or "")):
            why = f"mentions {base}"
        elif mention and _names_other_file(c.statement, base):
            continue  # "owns socketio_handler.py" isn't about monitoring.py, however close they sit in a ticket
        elif mention and any(_quoted_near(ce.quote or "", u.text, mention) for ce, u, _ in cited):
            why = f"quoted next to a mention of {base}"
        elif topic and (topic.search(c.statement) or topic.search(c.subject or "")):
            why = f"about {stem}"
        if not why:
            continue
        shown.append(CodeClaim(
            id=c.id, type=c.type.value, grade=c.grade.value, status=c.status.value, statement=c.statement,
            subject=c.subject or "", owner_name=c.owner_name or "", why=why,
            sources=[CodeSource(kind=u.kind, title=u.title, permalink=u.permalink, source_name=s,
                                occurred_at=u.occurred_at) for _, u, s in cited][:5],
            url=None if approved_only else f"{web}/projects/{project_id}/ledger?q={quote(c.statement[:80])}"))
    shown.sort(key=lambda x: (TYPE_ORDER.index(x.type) if x.type in TYPE_ORDER else 99,
                              -{"verified": 5, "attested": 4, "supported": 3}.get(x.grade, 0)))
    # Claims about this path that the reader may not see are counted, not shown.
    visible_ids = {c.id for c in visible}
    withheld = sum(1 for c in all_current if c.id not in visible_ids and any(
        ce.evidence_id in hit_ids for ce in c.evidence))

    return CodeContext(
        path=path, folder=folder, found=bool(hits or shown), owners=owners, commits=len(commits),
        last_change=max((c.occurred_at for c in commits if c.occurred_at), default=None),
        claims=shown, counts=dict(Counter(c.type for c in shown)), withheld=withheld, approved_only=approved_only,
        project_url=f"{web}/projects/{project_id}", repo_commits=repo_commits, created_by=created_by,
        created_at=first.occurred_at if first else None)


def _current_claims(db: DB, project_id: uuid.UUID) -> tuple[list[Claim], uuid.UUID | None]:
    run_id = rag.latest_run_id(db, project_id)
    if run_id is None:
        return [], None
    claims = db.scalars(select(Claim).where(Claim.run_id == run_id, Claim.status != ClaimStatus.rejected)).all()
    ids = {c.id for c in claims}
    return [c for c in claims if c.superseded_by not in ids], run_id


# --- one claim -----------------------------------------------------------------------------


class ClaimQuote(BaseModel):
    quote: str
    title: str
    kind: str
    author: str
    permalink: str
    source_name: str
    occurred_at: datetime | None


class ClaimDetail(BaseModel):
    id: uuid.UUID
    type: str
    grade: str
    grade_reason: str
    status: str
    statement: str
    rationale: str
    subject: str
    owner_name: str
    quotes: list[ClaimQuote]
    url: str | None


@router.get("/projects/{project_id}/claims/{claim_id}", response_model=ClaimDetail)
def get_claim(project_id: uuid.UUID, claim_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    visible, cites = rag.visible_claims(db, p, project_id)
    c = next((x for x in visible if x.id == claim_id), None)
    approved_only = not policy.can_view_ledger(p)
    if c is None or (approved_only and c.status not in (ClaimStatus.approved, ClaimStatus.edited)):
        raise HTTPException(404, "Claim not found, or not one you can see.")
    audit.record(db, actor_id=user.id, action="editor.claim", object_type="claim", object_id=c.id,
                 project_id=project_id)
    db.commit()
    web = get_settings().web_url.rstrip("/")
    return ClaimDetail(
        id=c.id, type=c.type.value, grade=c.grade.value, grade_reason=c.grade_reason, status=c.status.value,
        statement=c.statement, rationale=c.rationale or "", subject=c.subject or "", owner_name=c.owner_name or "",
        quotes=[ClaimQuote(quote=ce.quote, title=u.title, kind=u.kind, author=u.author, permalink=u.permalink,
                           source_name=s, occurred_at=u.occurred_at) for ce, u, s in cites.get(c.id, [])],
        url=None if approved_only else f"{web}/projects/{project_id}/ledger?q={quote(c.statement[:80])}")

