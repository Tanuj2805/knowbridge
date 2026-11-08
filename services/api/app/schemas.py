"""Request and response shapes for the HTTP API."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Role, Sensitivity, SourceKind, SourceStatus


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
    claim_count: int


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
