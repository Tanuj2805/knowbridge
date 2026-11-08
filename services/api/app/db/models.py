"""Database schema. See docs/BUILD_PLAN.md §4 for what each table is for."""

import enum
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 768  # changing this needs a migration


class Base(DeclarativeBase):
    pass


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _enum(e: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR so adding a value never needs an ALTER TYPE.
    return Enum(e, native_enum=False, length=32, values_callable=lambda x: [m.value for m in x])


# --- enums --------------------------------------------------------------


class Role(str, enum.Enum):
    admin = "admin"
    approver = "approver"
    leaver = "leaver"
    successor = "successor"
    viewer = "viewer"


class SourceKind(str, enum.Enum):
    github = "github"
    document = "document"
    taskboard = "taskboard"
    chat = "chat"
    meeting = "meeting"  # uploaded transcripts (Meet, Zoom, Teams, Otter, notes)
    interview = "interview"  # Gap Interview answers become evidence too


class SourceStatus(str, enum.Enum):
    pending = "pending"
    syncing = "syncing"
    ready = "ready"
    failed = "failed"


class Sensitivity(str, enum.Enum):
    team = "team"
    restricted = "restricted"
    confidential = "confidential"


class ClaimType(str, enum.Enum):
    decision = "decision"
    owner = "owner"
    dependency = "dependency"
    risk = "risk"
    blocker = "blocker"
    open_question = "open_question"
    next_action = "next_action"
    contact = "contact"
    recurring_problem = "recurring_problem"


class Grade(str, enum.Enum):
    verified = "verified"
    supported = "supported"
    attested = "attested"
    inferred = "inferred"
    conflicting = "conflicting"
    missing = "missing"


class ClaimStatus(str, enum.Enum):
    draft = "draft"
    edited = "edited"
    approved = "approved"
    rejected = "rejected"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    waiting = "waiting"  # paused for a human (Gap Interview)
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class HandoverStatus(str, enum.Enum):
    drafting = "drafting"
    interviewing = "interviewing"
    in_review = "in_review"
    published = "published"
    acknowledged = "acknowledged"


class QuestionStatus(str, enum.Enum):
    open = "open"
    answered = "answered"
    skipped = "skipped"
    reassigned = "reassigned"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


# --- people & projects --------------------------------------------------


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    auth_provider: Mapped[str] = mapped_column(String(32), default="demo")
    created_at: Mapped[datetime] = _created()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()

    # The database cascades deletes (ON DELETE CASCADE); don't let the ORM null the FKs.
    memberships: Mapped[list["Membership"]] = relationship(back_populates="project", passive_deletes=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", "role"),)
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(_enum(Role))
    # What kind of handover this person would receive, e.g. "backend", "treasurer".
    role_template: Mapped[str | None] = mapped_column(String(64))
    # Extra sensitivity labels this member is cleared for beyond their role.
    clearances: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    created_at: Mapped[datetime] = _created()

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()


# --- evidence -----------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind))
    name: Mapped[str] = mapped_column(String(200))
    # Connector settings. Never holds tokens (see `secret`).
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Encrypted credential (app.secretbox), e.g. a Jira API token. Never returned by the API.
    secret: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SourceStatus] = mapped_column(_enum(SourceStatus), default=SourceStatus.pending)
    status_detail: Mapped[str] = mapped_column(Text, default="")
    default_sensitivity: Mapped[Sensitivity] = mapped_column(
        _enum(Sensitivity), default=Sensitivity.team
    )
    # Who could see this at the source. Empty list = every project member.
    readers: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    scope_from: Mapped[date | None] = mapped_column(Date)
    scope_to: Mapped[date | None] = mapped_column(Date)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class EvidenceUnit(Base):
    __tablename__ = "evidence_units"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_evidence_tsv", "tsv", postgresql_using="gin"),
        Index("ix_evidence_text_trgm", "text", postgresql_using="gin", postgresql_ops={"text": "gin_trgm_ops"}),
        Index(
            "ix_evidence_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # Stable id inside the source (commit sha, message id, file path#chunk) for re-sync.
    external_id: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40))  # commit, pr, pr_comment, issue, doc_chunk, ...
    title: Mapped[str] = mapped_column(String(500), default="")
    permalink: Mapped[str] = mapped_column(String(1000), default="")
    locator: Mapped[str] = mapped_column(String(200), default="")  # line range, message #, sha
    author: Mapped[str] = mapped_column(String(200), default="")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    text: Mapped[str] = mapped_column(Text)  # already redacted by Sentinel
    content_hash: Mapped[str] = mapped_column(String(64))
    sensitivity: Mapped[Sensitivity] = mapped_column(_enum(Sensitivity), default=Sensitivity.team)
    language: Mapped[str] = mapped_column(String(16), default="en")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Which model made `embedding`; vectors from different models aren't comparable.
    embedding_model: Mapped[str | None] = mapped_column(String(120), index=True)
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', coalesce(title,'') || ' ' || text)", persisted=True)
    )
    created_at: Mapped[datetime] = _created()


class Redaction(Base):
    """Where Sentinel masked something. Records the rule, never the value."""

    __tablename__ = "redactions"
    id: Mapped[uuid.UUID] = _uuid()
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))  # secret | pii
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)


# --- memory graph -------------------------------------------------------


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("project_id", "kind", "key"),)
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # person, module, task, external_contact, ...
    key: Mapped[str] = mapped_column(String(200))  # normalised name for de-duplication
    name: Mapped[str] = mapped_column(String(300))
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)


class Edge(Base):
    __tablename__ = "edges"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    src_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="SET NULL")
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))


# --- claim ledger -------------------------------------------------------


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    type: Mapped[ClaimType] = mapped_column(_enum(ClaimType), index=True)
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")  # the "why" for decisions
    alternatives: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    subject: Mapped[str] = mapped_column(String(300), default="")  # module / person / task
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade: Mapped[Grade] = mapped_column(_enum(Grade), default=Grade.inferred, index=True)
    grade_reason: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    impact: Mapped[int] = mapped_column(Integer, default=2)  # 1 low .. 3 high
    status: Mapped[ClaimStatus] = mapped_column(
        _enum(ClaimStatus), default=ClaimStatus.draft, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL")
    )
    conflicts_with: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    # Strictest label among its evidence; recomputed whenever evidence changes.
    sensitivity: Mapped[Sensitivity] = mapped_column(_enum(Sensitivity), default=Sensitivity.team)
    source_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_agent: Mapped[str] = mapped_column(String(40), default="")
    owner_name: Mapped[str] = mapped_column(String(200), default="")  # for next actions / risks
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence: Mapped[list["ClaimEvidence"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_id", "evidence_id"),)
    id: Mapped[uuid.UUID] = _uuid()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="CASCADE"), index=True
    )
    quote: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    quote_hash: Mapped[str] = mapped_column(String(64))
    # Skeptic's judgement: supports | contradicts | unrelated | pending
    stance: Mapped[str] = mapped_column(String(16), default="pending")
    stance_note: Mapped[str] = mapped_column(Text, default="")

    claim: Mapped[Claim] = relationship(back_populates="evidence")
    unit: Mapped[EvidenceUnit] = relationship()


class ClaimVersion(Base):
    __tablename__ = "claim_versions"
    id: Mapped[uuid.UUID] = _uuid()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[ClaimStatus] = mapped_column(_enum(ClaimStatus))
    grade: Mapped[Grade] = mapped_column(_enum(Grade))
    note: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[datetime] = _created()


# --- runs ---------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    handover_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("handovers.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), default="reconstruct")
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), default=RunStatus.queued)
    status_detail: Mapped[str] = mapped_column(Text, default="")
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    steps: Mapped[list["RunStep"]] = relationship(order_by="RunStep.started_at")


class RunStep(Base):
    __tablename__ = "run_steps"
    id: Mapped[uuid.UUID] = _uuid()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="running")
    summary: Mapped[str] = mapped_column(Text, default="")
    items_in: Mapped[int] = mapped_column(Integer, default=0)
    items_out: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- handover -----------------------------------------------------------


class Handover(Base):
    __tablename__ = "handovers"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    leaver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    successor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role_template: Mapped[str] = mapped_column(String(64), default="general")
    # Partial handover: limit to modules / paths / task labels. Empty = whole project.
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    leaver_last_day: Mapped[date | None] = mapped_column(Date)
    leaver_available: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[HandoverStatus] = mapped_column(
        _enum(HandoverStatus), default=HandoverStatus.drafting
    )
    version: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()

    leaver: Mapped[User] = relationship(foreign_keys=[leaver_id])
    successor: Mapped[User] = relationship(foreign_keys=[successor_id])
    approver: Mapped[User] = relationship(foreign_keys=[approver_id])


class GapQuestion(Base):
    __tablename__ = "gap_questions"
    id: Mapped[uuid.UUID] = _uuid()
    handover_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("handovers.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    why_asked: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher first
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[QuestionStatus] = mapped_column(
        _enum(QuestionStatus), default=QuestionStatus.open
    )
    answer: Mapped[str] = mapped_column(Text, default="")
    answered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class HandoverSection(Base):
    """One section of a composed pack, for one recipient, at one handover version."""

    __tablename__ = "handover_sections"
    __table_args__ = (UniqueConstraint("handover_id", "recipient_id", "version", "key"),)
    id: Mapped[uuid.UUID] = _uuid()
    handover_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("handovers.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(40))  # brief, ownership, decisions, risks, ...
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    # {"blocks": [{"text": "...", "claim_ids": [...]}, ...]}
    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    withheld: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"count": 2, "labels": [...]}
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[uuid.UUID] = _uuid()
    handover_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("handovers.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)  # 1..4
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    owner_name: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[date | None] = mapped_column(Date)
    claim_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class ClaimFlag(Base):
    """A successor saying "I think this is wrong" — goes back to the approver."""

    __tablename__ = "claim_flags"
    id: Mapped[uuid.UUID] = _uuid()
    handover_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("handovers.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    raised_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


# --- audit, jobs, app state --------------------------------------------


class AppState(Base):
    """Small key/value store, e.g. the OpenFGA store id and model hash."""

    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = _uuid()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))  # claim.approve, pack.view, pack.export, ...
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = _created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_pick", "status", "run_after"),)
    id: Mapped[uuid.UUID] = _uuid()
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str] = mapped_column(Text, default="")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
