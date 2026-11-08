import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import audit, gatekeeper, jobs, secretbox, storage
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.config import get_settings
from app.connectors import ConnectorError
from app.connectors.github import GitHubLive
from app.connectors.jira import JiraLive
from app.db.models import Membership, Sensitivity, Source, SourceKind, SourceStatus
from app.gatekeeper import policy, require
from app.schemas import SourceOut, SourceUpdate

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])

ALLOWED_EXT = {
    SourceKind.github: {".json", ".yaml", ".yml"},
    SourceKind.document: {".md", ".markdown", ".txt", ".pdf", ".docx"},
    SourceKind.taskboard: {".json", ".csv"},
    SourceKind.chat: {".txt", ".json", ".zip"},
    SourceKind.meeting: {".vtt", ".srt", ".txt", ".docx", ".md"},
}


def _check_readers(db: DB, project_id: uuid.UUID, readers: list[uuid.UUID]) -> list[uuid.UUID]:
    if not readers:
        return []
    members = set(db.scalars(select(Membership.user_id).where(Membership.project_id == project_id)))
    unknown = set(readers) - members
    if unknown:
        raise HTTPException(422, "Everyone who can see a source must be on the project.")
    return sorted(set(readers))


def _get(db: DB, project_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.project_id != project_id:
        raise HTTPException(404, "Source not found.")
    return source


async def _check_jira(site: str, email: str, token: str, jql: str) -> tuple[str, str]:
    """Validates the connection before anything is saved. Returns (normalised site, account name)."""
    try:
        client = JiraLive(site, email.strip(), token.strip(), jql)
        account = await run_in_threadpool(client.whoami)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    return client.site, account


async def _check_github(repo: str, token: str) -> dict:
    """Can we read this repository with this token? Returns what to keep in the source config."""
    try:
        info = await run_in_threadpool(GitHubLive(repo, token or get_settings().github_token).check)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    if info["visibility"] == "private" and not token and not get_settings().github_token:
        raise HTTPException(422, "This repository is private. Add a read-only token.")
    return info


async def _store_files(project_id: uuid.UUID, source: Source, files: list[UploadFile]) -> list[str]:
    names = []
    for f in files:
        name = storage.safe_name(f.filename or "upload")
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXT[source.kind]:
            raise HTTPException(
                422, f"{name}: this source takes {', '.join(sorted(ALLOWED_EXT[source.kind]))} files."
            )
        data = await f.read(storage.MAX_UPLOAD_BYTES + 1)
        if len(data) > storage.MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{name} is larger than 25 MB.")
        storage.save_upload(project_id, source.id, name, data)
        names.append(name)
    return names


@router.get("", response_model=list[SourceOut])
def list_sources(project_id: uuid.UUID, p: ProjectPrincipal, db: DB):
    require(policy.can_view_ledger(p), "Only admins and approvers can see sources.")
    return db.scalars(select(Source).where(Source.project_id == project_id).order_by(Source.created_at)).all()


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    project_id: uuid.UUID,
    p: ProjectPrincipal,
    user: CurrentUser,
    db: DB,
    kind: Annotated[SourceKind, Form()],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    default_sensitivity: Annotated[Sensitivity, Form()] = Sensitivity.team,
    readers: Annotated[list[uuid.UUID] | None, Form()] = None,
    repo: Annotated[str | None, Form()] = None,
    scope_from: Annotated[date | None, Form()] = None,
    scope_to: Annotated[date | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    jira_site: Annotated[str | None, Form(max_length=300)] = None,
    jira_email: Annotated[str | None, Form(max_length=320)] = None,
    jira_token: Annotated[str | None, Form(max_length=500)] = None,
    jql: Annotated[str | None, Form(max_length=2000)] = None,
    github_token: Annotated[str | None, Form(max_length=500)] = None,
    meeting_date: Annotated[date | None, Form()] = None,
):
    require(policy.can_manage_project(p), "Only a project admin can connect sources.")
    if kind == SourceKind.interview:
        raise HTTPException(422, "Interview answers are added by KnowBridge, not uploaded.")
    files = [f for f in (files or []) if f.filename]
    repo = (repo or "").strip().removeprefix("https://github.com/").strip("/") or None
    jira = kind == SourceKind.taskboard and bool((jira_site or "").strip())
    if kind == SourceKind.github and not repo and not files:
        raise HTTPException(422, "Give the repository as owner/name, or upload a repository snapshot.")
    if kind != SourceKind.github and not jira and not files:
        raise HTTPException(422, "Choose at least one file to upload.")
    config: dict = {}
    secret = None
    if kind == SourceKind.github and repo and not files:
        token = (github_token or "").strip()
        info = await _check_github(repo, token)
        config = {"repo": info["repo"], "visibility": info["visibility"], "default_branch": info["default_branch"],
                  "account": info.get("account", ""), "uses_own_token": bool(token)}
        if info.get("warning"):
            config["warning"] = info["warning"]
        secret = secretbox.seal(token) if token else None
    if kind == SourceKind.meeting and meeting_date:
        config["meeting_date"] = meeting_date.isoformat()  # used when a transcript doesn't say its date
    if jira:
        site, account = await _check_jira(jira_site or "", jira_email or "", jira_token or "", jql or "")
        config = {"provider": "jira", "site": site, "email": (jira_email or "").strip(), "jql": (jql or "").strip(),
                  "account": account}
        secret = secretbox.seal((jira_token or "").strip())
        files = []
    if scope_from and scope_to and scope_from > scope_to:
        raise HTTPException(422, "The start date is after the end date.")

    source = Source(
        project_id=project_id,
        kind=kind,
        name=name.strip(),
        config=config,
        secret=secret,
        default_sensitivity=default_sensitivity,
        readers=_check_readers(db, project_id, readers or []),
        scope_from=scope_from,
        scope_to=scope_to,
        created_by=user.id,
    )
    db.add(source)
    db.flush()
    try:
        stored = await _store_files(project_id, source, files)
    except HTTPException:
        storage.delete_source_files(project_id, source.id)
        raise
    source.config = {**source.config, "files": stored} if stored else source.config
    jobs.enqueue(db, "source.sync", {"source_id": source.id})
    audit.record(db, actor_id=user.id, action="source.connect", object_type="source", object_id=source.id,
                 project_id=project_id, kind=kind.value, name=source.name, files=stored, repo=repo,
                 jira_site=config.get("site"), jql=config.get("jql"))
    db.commit()
    gatekeeper.sync_source(db, source)
    return source


@router.post("/{source_id}/files", response_model=SourceOut)
async def add_files(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    p: ProjectPrincipal,
    user: CurrentUser,
    db: DB,
    files: Annotated[list[UploadFile], File()],
):
    require(policy.can_manage_project(p), "Only a project admin can change sources.")
    source = _get(db, project_id, source_id)
    if source.config.get("repo") or source.config.get("provider") == "jira":
        raise HTTPException(422, "This source reads live from its tool; there's nothing to upload.")
    stored = await _store_files(project_id, source, [f for f in files if f.filename])
    source.config = {**source.config, "files": sorted(set(source.config.get("files", [])) | set(stored))}
    source.status = SourceStatus.pending
    jobs.enqueue(db, "source.sync", {"source_id": source.id})
    audit.record(db, actor_id=user.id, action="source.add_files", object_type="source", object_id=source.id,
                 project_id=project_id, files=stored)
    db.commit()
    return source


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    project_id: uuid.UUID, source_id: uuid.UUID, body: SourceUpdate, p: ProjectPrincipal, user: CurrentUser, db: DB
):
    require(policy.can_manage_project(p), "Only a project admin can change sources.")
    source = _get(db, project_id, source_id)
    previous_readers = list(source.readers or [])
    changes = body.model_dump(exclude_unset=True)
    resync = False
    if "name" in changes and body.name:
        source.name = body.name.strip()
    if "default_sensitivity" in changes and body.default_sensitivity:
        resync |= body.default_sensitivity != source.default_sensitivity
        source.default_sensitivity = body.default_sensitivity
    if "readers" in changes:
        source.readers = _check_readers(db, project_id, body.readers or [])
    for field in ("scope_from", "scope_to"):
        if field in changes:
            resync |= getattr(source, field) != changes[field]
            setattr(source, field, changes[field])
    if source.scope_from and source.scope_to and source.scope_from > source.scope_to:
        raise HTTPException(422, "The start date is after the end date.")
    changes.pop("token", None)  # never into the audit log
    provider = "jira" if source.config.get("provider") == "jira" else "github" if source.config.get("repo") else None
    if body.jql and provider != "jira":
        raise HTTPException(422, "Only Jira sources have a JQL filter.")
    if body.token or body.jql:
        if provider is None:
            raise HTTPException(422, "Only live GitHub and Jira sources have a token.")
        try:
            token = body.token.strip() if body.token else secretbox.unseal(source.secret) if source.secret else ""
        except secretbox.SecretUnreadable as e:
            raise HTTPException(422, str(e)) from e
        if provider == "jira":
            jql = (body.jql or source.config["jql"]).strip()
            _, account = await _check_jira(source.config["site"], source.config["email"], token, jql)
            source.config = {**source.config, "jql": jql, "account": account}
        else:
            info = await _check_github(source.config["repo"], token)
            source.config = {k: v for k, v in source.config.items() if k != "warning"} | {
                "account": info.get("account", ""), "uses_own_token": bool(token),
                **({"warning": info["warning"]} if info.get("warning") else {}),
            }
        if body.token:
            source.secret = secretbox.seal(token)
            changes["token_rotated"] = True
        resync = True
    if resync:
        source.status = SourceStatus.pending
        jobs.enqueue(db, "source.sync", {"source_id": source.id})
    audit.record(db, actor_id=user.id, action="source.update", object_type="source", object_id=source.id,
                 project_id=project_id, **{k: str(v) for k, v in changes.items()})
    db.commit()
    if "readers" in changes:
        gatekeeper.sync_source(db, source, previous_readers=previous_readers)
    return source


@router.post("/{source_id}/sync", response_model=SourceOut)
def resync(
    project_id: uuid.UUID, source_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB, full: bool = False
):
    """Live sources normally fetch only what changed; full=true re-reads everything
    (and notices items deleted at the source)."""
    require(policy.can_manage_project(p), "Only a project admin can sync sources.")
    source = _get(db, project_id, source_id)
    if source.status == SourceStatus.syncing:
        raise HTTPException(409, "This source is already syncing.")
    source.status = SourceStatus.pending
    source.status_detail = "Waiting to sync…"
    jobs.enqueue(db, "source.sync", {"source_id": source.id, **({"full": True} if full else {})})
    audit.record(db, actor_id=user.id, action="source.sync", object_type="source", object_id=source.id,
                 project_id=project_id, full=full)
    db.commit()
    return source


@router.delete("/{source_id}", status_code=204)
def delete_source(project_id: uuid.UUID, source_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    require(policy.can_manage_project(p), "Only a project admin can remove sources.")
    source = _get(db, project_id, source_id)
    audit.record(db, actor_id=user.id, action="source.remove", object_type="source", object_id=source.id,
                 project_id=project_id, name=source.name, items=source.item_count)
    db.delete(source)
    db.commit()
    storage.delete_source_files(project_id, source_id)
