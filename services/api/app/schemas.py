"""Request and response shapes for the HTTP API."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    ClaimStatus,
    ClaimType,
    Grade,
    HandoverStatus,
    QuestionStatus,
    Role,
    RunStatus,
    Sensitivity,
    SourceKind,
    SourceStatus,
)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(Out):
    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None = None


class MemberOut(Out):
    user: UserOut
    roles: list[Role]
    role_template: str | None = None
    clearances: list[str] = []


class ProjectOut(Out):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    retention_days: int
    created_at: datetime


class ProjectSummary(ProjectOut):
    my_roles: list[Role]
    member_count: int
    source_count: int
    evidence_count: int
    claim_count: int  # current claims of the latest finished run (not every claim ever made)
    handover_count: int = 0
    interviewed_count: int = 0  # handovers whose Gap Interview has no open questions left
    published_count: int = 0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)


class MemberUpsert(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    roles: list[Role] = Field(min_length=1)
    role_template: str | None = Field(default=None, max_length=64)
    clearances: list[str] = []


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    token: str | None = Field(default=None, max_length=500)  # rotate a Jira / GitHub token
    jql: str | None = Field(default=None, max_length=2000)
    default_sensitivity: Sensitivity | None = None
    readers: list[uuid.UUID] | None = None
    scope_from: date | None = None
    scope_to: date | None = None


class EvidenceOut(Out):
    id: uuid.UUID
    source_id: uuid.UUID
    kind: str
    title: str
    permalink: str
    locator: str
    author: str
    occurred_at: datetime | None
    sensitivity: Sensitivity
    language: str
    removed: bool = False


class RelatedHit(BaseModel):
    """Another match inside the same issue, PR or card (usually a comment)."""

    id: uuid.UUID
    kind: str
    title: str
    locator: str
    author: str
    occurred_at: datetime | None
    snippet: str


class EvidenceHit(EvidenceOut):
    snippet: str
    score: float | None = None
    strength: str | None = None  # "strong" | "possible" (search results only)
    related: list[RelatedHit] = []


class EvidencePage(BaseModel):
    items: list[EvidenceHit]
    total: int | None  # None for search results (ranked, not counted)
    hidden: int  # units in this project the caller isn't allowed to see


class RedactionOut(Out):
    category: str
    rule_id: str
    start: int
    end: int


class EvidenceDetail(EvidenceOut):
    text: str
    source_name: str
    source_kind: SourceKind
    redactions: list[RedactionOut]
    label_reasons: list[str] = []
    meta: dict
    context: list[EvidenceHit] = []
    linked: list[EvidenceHit] = []  # same Jira key: the issue, and commits/PRs/messages that mention it


class EvidenceRelabel(BaseModel):
    sensitivity: Sensitivity


class SourceOut(Out):
    id: uuid.UUID
    kind: SourceKind
    name: str
    status: SourceStatus
    status_detail: str
    default_sensitivity: Sensitivity
    readers: list[uuid.UUID]
    scope_from: date | None
    scope_to: date | None
    item_count: int
    last_synced_at: datetime | None
    created_at: datetime
    config: dict


# --- runs and the claim ledger ----------------------------------------------


class RunStepOut(Out):
    agent: str
    status: str
    summary: str
    items_in: int
    items_out: int
    llm_calls: int
    tokens: int
    error: str
    started_at: datetime
    finished_at: datetime | None
    progress: dict | None = None  # {"done": 12, "total": 33}: model calls, while it works


class RunOut(Out):
    id: uuid.UUID
    status: RunStatus
    status_detail: str
    llm_calls: int
    tokens_used: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    started_by_name: str = ""
    steps: list[RunStepOut] = []


class ClaimCite(BaseModel):
    evidence_id: uuid.UUID
    quote: str
    kind: str
    title: str
    locator: str
    author: str
    occurred_at: datetime | None
    permalink: str
    source_name: str


class ClaimRef(BaseModel):
    """Another claim, as shown next to this one (what it replaced, what it disagrees with)."""

    id: uuid.UUID
    statement: str
    valid_from: datetime | None
    valid_to: datetime | None = None
    grade: Grade


class ClaimOut(Out):
    id: uuid.UUID
    type: ClaimType
    statement: str
    rationale: str
    alternatives: list[str]
    subject: str
    owner_name: str
    due_date: date | None
    valid_from: datetime | None
    grade: Grade
    grade_reason: str
    impact: int
    status: ClaimStatus
    sensitivity: Sensitivity
    created_by_agent: str
    from_system_data: bool = False
    checked: bool = False  # the Skeptic has graded it
    version: int = 1
    reviewed_by_name: str = ""
    reviewed_at: datetime | None = None
    review_note: str = ""
    skeptic_note: str = ""
    replaces: list[ClaimRef] = []  # earlier claims this one changed
    replaced_by: ClaimRef | None = None
    conflicts: list[ClaimRef] = []
    evidence: list[ClaimCite] = []


class LedgerPage(BaseModel):
    run: RunOut | None
    llm_ready: bool
    items: list[ClaimOut]
    total: int = 0  # claims matching the filters; `items` is one page of them
    counts: dict[str, int]  # by claim type, among current claims this person can see
    grades: dict[str, int] = {}  # by grade, same claims
    replaced: int = 0  # earlier versions shown under the claim that replaced them
    removed: int = 0  # claims set aside: by the Skeptic, the Gap Interview, or a reviewer
    review: dict[str, int] = {}  # {"todo": drafts to review, "approved": approved or edited}
    can_review: bool = False
    hidden: int  # claims that cite something this person can't see


# --- handovers and the Gap Interview ----------------------------------------


class HandoverCreate(BaseModel):
    leaver_id: uuid.UUID
    successor_id: uuid.UUID
    approver_id: uuid.UUID
    leaver_last_day: date | None = None
    title: str = Field(default="", max_length=300)


class QuestionClaim(BaseModel):
    id: uuid.UUID
    statement: str
    grade: Grade
    evidence: list[ClaimCite] = []


class QuestionOut(BaseModel):
    id: uuid.UUID
    position: int
    question: str
    why_asked: str
    kind: str  # choose | confirm | fill
    status: QuestionStatus
    answer: str  # as stored: masked by Sentinel
    answered_by_name: str = ""
    answered_at: datetime | None
    assignee: UserOut
    claims: list[QuestionClaim] = []
    verdict: str = ""  # how the answer was read: confirms, corrects, picks_a…
    effects: list[str] = []  # what changed in the ledger


class HandoverOut(BaseModel):
    id: uuid.UUID
    title: str
    status: HandoverStatus
    leaver: UserOut
    successor: UserOut
    approver: UserOut
    leaver_last_day: date | None
    created_at: datetime
    questions_total: int = 0
    questions_answered: int = 0
    questions_open: int = 0
    my_open: int = 0  # open questions assigned to the person asking


class HandoverDetail(HandoverOut):
    questions: list[QuestionOut] = []
    claims_ready: bool  # a finished "build claims" run exists
    can_manage: bool
    preparing: bool  # the questions are being written
    approved_claims: int = 0  # approved or edited, current, in the latest run
    latest_version: int = 0  # newest composed pack (may be a preview)
    published_version: int = 0
    composing: bool = False
    can_publish: bool = False  # the handover's approver
    open_flags: int = 0


class AnswerIn(BaseModel):
    action: Literal["answer", "skip", "reassign"]
    answer: str = Field(default="", max_length=4000)
    assignee_id: uuid.UUID | None = None


class ClaimReview(BaseModel):
    action: Literal["approve", "edit", "reject", "reopen"]
    statement: str | None = Field(default=None, min_length=3, max_length=1000)
    rationale: str | None = Field(default=None, max_length=2000)
    owner_name: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    note: str = Field(default="", max_length=500)


class BulkReview(BaseModel):
    """Approve many drafts at once: the given ids, every draft with one of the given grades, or all of them."""

    ids: list[uuid.UUID] = []
    grades: list[Grade] = []
    all: bool = False  # every current draft the reviewer can see


class PackSectionOut(BaseModel):
    id: uuid.UUID
    key: str
    title: str
    intro: str
    blocks: list[dict]
    withheld: dict
    acknowledged_at: datetime | None


class PlanItemOut(Out):
    id: uuid.UUID
    week: int
    title: str
    detail: str
    owner_name: str
    due_date: date | None
    done: bool
    claim_ids: list[uuid.UUID]


class FlagOut(BaseModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    statement: str
    note: str
    raised_by_name: str
    created_at: datetime
    resolved: bool


class PackOut(BaseModel):
    version: int
    published_version: int
    is_published: bool
    title: str
    leaver: UserOut
    successor: UserOut
    approver: UserOut
    leaver_last_day: date | None
    sections: list[PackSectionOut]
    plan: list[PlanItemOut]
    flags: list[FlagOut] = []
    can_acknowledge: bool = False  # the person taking over, on the published version
    can_publish: bool = False


class FlagIn(BaseModel):
    claim_id: uuid.UUID
    note: str = Field(min_length=3, max_length=1000)


class PlanDoneIn(BaseModel):
    done: bool

