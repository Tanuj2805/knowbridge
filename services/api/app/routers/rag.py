"""Ask the project (RAG): questions answered from the project's own record, with sources, and the
same retrieval for other models: ranked chunks with a ready context, or the whole project as one file.

Anyone in the project may ask. Admins and approvers search every current claim; everyone else
only approved ones. Either way only evidence that person may open is used.

Guardrails (app/guard.py) run inside the answer; here: the assistant's past turns must carry this
server's signature, each person has a request limit, and whatever the guard did is audited.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import audit, guard, jobs, rag
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.config import get_settings
from app.db.models import AuditEvent, Project
from app.gatekeeper import policy, require

router = APIRouter(prefix="/projects/{project_id}/rag", tags=["ask"])


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)
    # the signature this server gave an answer; an assistant turn without a valid one is dropped
    token: str | None = Field(default=None, max_length=64)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    approved_only: bool = False
    # the chat so far, oldest first (the client keeps it); the last few turns are used
    history: list[TurnIn] = Field(default_factory=list, max_length=40)


class RetrieveIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=12, ge=1, le=40)
    budget_tokens: int = Field(default=4000, ge=500, le=32000)
    approved_only: bool = False


def _project(db: DB, p, project_id: uuid.UUID) -> Project:
    require(p.is_member, "You're not in this project.")
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "No such project.")
    return project


def _approved_only(p, asked: bool) -> bool:
    return asked or not policy.can_view_ledger(p)


def _rate_limit(db: DB, user_id: uuid.UUID, action: str, per_minute: int, per_day: int) -> None:
    """Each request is in the audit log anyway, so the log is the counter: works across workers."""
    now = datetime.now(UTC)

    def count(since: datetime) -> int:
        return db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.actor_id == user_id, AuditEvent.action == action, AuditEvent.at >= since)) or 0

    if per_minute and count(now - timedelta(minutes=1)) >= per_minute:
        raise HTTPException(429, "That's a lot of questions in a minute. Wait a moment and try again.")
    if per_day and count(now - timedelta(days=1)) >= per_day:
        raise HTTPException(429, "You've reached today's limit for questions. It resets within 24 hours.")


def _chunk_out(ch: rag.Chunk) -> dict:
    meta = {k: v for k, v in ch.meta.items() if k != "guarded"}
    return {"ref": ch.ref, "kind": ch.kind, "id": str(ch.id), "title": ch.title, "text": ch.text,
            "sensitivity": ch.sensitivity.value, "score": round(ch.score, 4), **meta}


@router.get("/status")
def status(project_id: uuid.UUID, p: ProjectPrincipal, db: DB) -> dict:
    _project(db, p, project_id)
    s = get_settings()
    return {**rag.index_counts(db, project_id), "model": rag.ask_model(), "ready": rag.ask_ready(),
            "external": rag.ask_is_external(), "context_tokens": s.rag_context_tokens,
            "approved_only": not policy.can_view_ledger(p), "can_index": policy.can_view_ledger(p),
            "per_minute": s.rag_ask_per_minute}


@router.post("/index", status_code=202)
def reindex(project_id: uuid.UUID, p: ProjectPrincipal, db: DB) -> dict:
    require(policy.can_view_ledger(p), "Only admins and approvers can rebuild the index.")
    jobs.enqueue(db, "rag.index", {"project_id": project_id})  # claims
    jobs.enqueue(db, "project.embed", {"project_id": project_id})  # source items not in it yet
    db.commit()
    return {"queued": True}


@router.post("/ask")
def ask(project_id: uuid.UUID, body: AskIn, p: ProjectPrincipal, user: CurrentUser, db: DB) -> dict:
    project = _project(db, p, project_id)
    if not rag.ask_ready():
        raise HTTPException(409, "No AI model is set up. Add LLM_ASK_BASE_URL and LLM_ASK_MODEL, or GEMINI_API_KEY.")
    s = get_settings()
    _rate_limit(db, user.id, "rag.ask", s.rag_ask_per_minute, s.rag_ask_per_day)

    # The browser keeps the chat, so it could claim the assistant said anything: only answers this
    # server signed (for this person, in this project, word for word) go back to the model.
    history, forged = [], 0
    for t in body.history:
        if t.role == "assistant" and not guard.turn_is_ours(user.id, project_id, t.content, t.token):
            forged += 1
            continue
        history.append(rag.Turn(t.role, t.content))

    a = rag.answer(db, p, project, body.question.strip(), approved_only=_approved_only(p, body.approved_only),
                   history=history)
    notes = a.guard | ({"forged_turns": forged} if forged else {}) | (
        {"invented_ids": a.invented} if a.invented else {})
    audit.record(db, actor_id=user.id, action="rag.ask", object_type="project", object_id=project_id,
                 project_id=project_id, question=guard.clean(body.question)[:200], cited=len(a.cited), model=a.model)
    serious = {"question_blocked", "answer_blocked", "cleaned_sources", "forged_turns", "removed_links", "redacted"}
    if serious & notes.keys():
        audit.record(db, actor_id=user.id, action="rag.guard", object_type="project", object_id=project_id,
                     project_id=project_id, **{k: v for k, v in notes.items() if k in serious | {"cleaned_kinds"}})
    db.commit()
    return {
        "answer": a.text, "answerable": a.answerable, "error": a.error, "model": a.model, "cached": a.cached,
        "blocked": a.blocked, "guard": notes,
        "token": guard.sign_turn(user.id, project_id, a.text) if a.text else None,
        "citations": [_chunk_out(c) for c in a.cited],
        "sources": [_chunk_out(c) for c in a.context.chunks],
        "invented": a.invented, "withheld": a.context.withheld, "dropped": a.context.dropped,
    }


@router.post("/retrieve")
def retrieve(project_id: uuid.UUID, body: RetrieveIn, p: ProjectPrincipal, user: CurrentUser, db: DB) -> dict:
    """For any other model: the chunks most relevant to a query and a context block built from
    them (external label cap applied, every item through the guard), ready to put in a prompt."""
    project = _project(db, p, project_id)
    s = get_settings()
    _rate_limit(db, user.id, "rag.export", s.rag_export_per_minute, 0)
    found = rag.retrieve(db, p, project_id, guard.clean(body.query).strip(), k_claims=body.k,
                         k_evidence=max(4, body.k // 2), approved_only=_approved_only(p, body.approved_only))
    context = rag.build_context(project, found, budget_tokens=body.budget_tokens, external=True)
    audit.record(db, actor_id=user.id, action="rag.export", object_type="project", object_id=project_id,
                 project_id=project_id, format="retrieve", query=guard.clean(body.query)[:200],
                 items=len(context.chunks), cleaned=context.cleaned)
    db.commit()
    return {"chunks": [_chunk_out(c) for c in context.chunks], "context": context.text,
            "withheld": context.withheld, "dropped": context.dropped, "cleaned": context.cleaned}


@router.get("/context.md", response_class=PlainTextResponse)
def context_file(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB,
                 budget_tokens: int = Query(default=8000, ge=1000, le=100_000),
                 approved_only: bool = False) -> PlainTextResponse:
    """The whole project as one Markdown file to give any model as its knowledge."""
    project = _project(db, p, project_id)
    _rate_limit(db, user.id, "rag.export", get_settings().rag_export_per_minute, 0)
    text, included, left_out = rag.project_context(db, p, project, budget_tokens=budget_tokens,
                                                   approved_only=_approved_only(p, approved_only))
    audit.record(db, actor_id=user.id, action="rag.export", object_type="project", object_id=project_id,
                 project_id=project_id, format="markdown", items=included, left_out=left_out)
    db.commit()
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
