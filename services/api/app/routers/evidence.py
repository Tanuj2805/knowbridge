import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app import audit, embeddings, gatekeeper, jobs, retrieval
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.db.models import EvidenceUnit, Redaction, Sensitivity, Source
from app.gatekeeper import policy, require
from app.schemas import EvidenceDetail, EvidenceHit, EvidencePage, EvidenceRelabel, RedactionOut, RelatedHit

router = APIRouter(prefix="/projects/{project_id}/evidence", tags=["evidence"])


def _hit(u: EvidenceUnit, snippet: str, score: float | None = None) -> EvidenceHit:
    return EvidenceHit(
        id=u.id, source_id=u.source_id, kind=u.kind, title=u.title, permalink=u.permalink, locator=u.locator,
        author=u.author, occurred_at=u.occurred_at, sensitivity=u.sensitivity, language=u.language,
        removed=bool(u.meta.get("removed_at")), snippet=snippet, score=score,
    )


def _hidden_count(db: DB, p, project_id: uuid.UUID) -> int:
    total = db.scalar(select(func.count()).select_from(EvidenceUnit).where(EvidenceUnit.project_id == project_id))
    visible = db.scalar(
        select(func.count()).select_from(retrieval.visible_units(p, project_id, retrieval.Filters(
            include_removed=True)).subquery())
    )
    return max(0, (total or 0) - (visible or 0))


@router.get("", response_model=EvidencePage)
def list_evidence(
    project_id: uuid.UUID,
    p: ProjectPrincipal,
    db: DB,
    q: str | None = Query(default=None, max_length=300),
    source_id: uuid.UUID | None = None,
    kind: str | None = None,
    sensitivity: Sensitivity | None = None,
    language: str | None = None,
    author: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
):
    require(policy.can_view_ledger(p), "Only admins and approvers can browse evidence.")
    f = retrieval.Filters(source_id=source_id, kind=kind, sensitivity=sensitivity, language=language,
                          author=author)
    hidden = _hidden_count(db, p, project_id)
    if q and q.strip():
        hits = retrieval.search(db, p, project_id, q.strip(), f, limit=limit)
        items = []
        for h in hits:
            item = _hit(h.unit, h.snippet, h.score)
            item.strength = h.strength
            item.related = [
                RelatedHit(id=r.unit.id, kind=r.unit.kind, title=r.unit.title, locator=r.unit.locator,
                           author=r.unit.author, occurred_at=r.unit.occurred_at, snippet=r.snippet)
                for r in h.related
            ]
            items.append(item)
        return EvidencePage(items=items, total=None, hidden=hidden)

    base = retrieval.visible_units(p, project_id, f)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    units = db.scalars(
        base.order_by(EvidenceUnit.occurred_at.desc().nulls_last(), EvidenceUnit.id).offset(offset).limit(limit)
    ).all()
    allowed = gatekeeper.visible_evidence_ids(db, p, project_id, [u.id for u in units])
    return EvidencePage(
        items=[_hit(u, retrieval.snippet(u.text, "")) for u in units if u.id in allowed],
        total=total,
        hidden=hidden,
    )


@router.get("/stats")
def evidence_stats(project_id: uuid.UUID, p: ProjectPrincipal, db: DB):
    require(policy.can_view_ledger(p), "Only admins and approvers can see evidence stats.")
    base = retrieval.visible_units(p, project_id, retrieval.Filters()).subquery()
    by = lambda col: dict(db.execute(select(col, func.count()).group_by(col)).all())  # noqa: E731
    redactions = dict(
        db.execute(
            select(Redaction.category, func.count())
            .join(EvidenceUnit, EvidenceUnit.id == Redaction.evidence_id)
            .where(EvidenceUnit.project_id == project_id)
            .group_by(Redaction.category)
        ).all()
    )
    emb = embeddings.embedder()
    model_id = emb.model_id if emb else None
    sendable = embeddings.sendable_labels(emb) if emb else []
    return {
        "search_model": model_id,
        "search_external": bool(emb and emb.external),
        # items kept out of an external provider because of their label (keyword search only)
        "kept_private": db.scalar(
            select(func.count()).select_from(base).where(base.c.sensitivity.not_in(sendable))
        ) if emb and emb.external else 0,
        "embedded": db.scalar(
            select(func.count()).select_from(base).where(base.c.embedding_model == model_id)
        ) if model_id else 0,
        "by_kind": by(base.c.kind),
        "by_sensitivity": by(base.c.sensitivity),
        "by_language": by(base.c.language),
        "visible": db.scalar(select(func.count()).select_from(base)) or 0,
        "hidden": _hidden_count(db, p, project_id),
        "masked_secrets": redactions.get("secret", 0),
        "masked_pii": redactions.get("pii", 0),
    }


@router.post("/reindex", status_code=202)
def build_smart_search(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB) -> dict:
    """Builds meaning-search vectors for every item that doesn't have one from the current model."""
    require(policy.can_manage_project(p), "Only a project admin can rebuild search.")
    if embeddings.current_model_id() is None:
        raise HTTPException(409, "Smart search is turned off (EMBEDDING_PROVIDER=off).")
    jobs.enqueue(db, "project.embed", {"project_id": project_id})
    audit.record(db, actor_id=user.id, action="search.reindex", object_type="project", object_id=project_id,
                 project_id=project_id)
    db.commit()
    return {"queued": True}


def _visible_unit(db: DB, p, project_id: uuid.UUID, evidence_id: uuid.UUID) -> EvidenceUnit:
    unit = db.get(EvidenceUnit, evidence_id)
    # 404 rather than 403, so hidden items don't reveal that they exist.
    if (
        unit is None
        or unit.project_id != project_id
        or evidence_id not in gatekeeper.visible_evidence_ids(db, p, project_id, [evidence_id])
    ):
        raise HTTPException(404, "Evidence not found.")
    return unit


def _linked(db: DB, p, project_id: uuid.UUID, unit: EvidenceUnit, limit: int = 12) -> list[EvidenceHit]:
    """Jira issues this item mentions, or (for a Jira issue) the commits, PRs and messages
    that mention it. Keys only count if a real Jira issue with that key exists here."""
    base = retrieval.visible_units(p, project_id, retrieval.Filters())
    key = unit.meta.get("key") if unit.meta.get("provider") == "jira" else None
    if key:
        q = base.where(EvidenceUnit.meta["refs"].contains([key]), EvidenceUnit.id != unit.id)
    elif unit.meta.get("refs"):
        q = base.where(EvidenceUnit.meta["provider"].astext == "jira", EvidenceUnit.kind == "card",
                       EvidenceUnit.meta["key"].astext.in_(unit.meta["refs"]))
    else:
        return []
    found = db.scalars(q.order_by(EvidenceUnit.occurred_at.desc().nulls_last()).limit(limit)).all()
    allowed = gatekeeper.visible_evidence_ids(db, p, project_id, [u.id for u in found])
    return [_hit(u, u.text[:300]) for u in found if u.id in allowed]


@router.get("/{evidence_id}", response_model=EvidenceDetail)
def get_evidence(project_id: uuid.UUID, evidence_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    require(policy.can_view_ledger(p), "Only admins and approvers can browse evidence.")
    unit = _visible_unit(db, p, project_id, evidence_id)
    source = db.get(Source, unit.source_id)
    redactions = db.scalars(select(Redaction).where(Redaction.evidence_id == unit.id).order_by(Redaction.start)).all()

    context: list[EvidenceHit] = []
    if unit.kind in ("message", "meeting_segment") and unit.occurred_at:
        f = retrieval.Filters(source_id=unit.source_id)
        base = retrieval.visible_units(p, project_id, f).where(EvidenceUnit.id != unit.id)
        if unit.kind == "meeting_segment":  # the moments before and after, in the same meeting
            base = base.where(EvidenceUnit.meta["file"].astext == unit.meta.get("file"))
        before = db.scalars(base.where(EvidenceUnit.occurred_at <= unit.occurred_at)
                            .order_by(EvidenceUnit.occurred_at.desc()).limit(3)).all()
        after = db.scalars(base.where(EvidenceUnit.occurred_at > unit.occurred_at)
                           .order_by(EvidenceUnit.occurred_at).limit(3)).all()
        around = [*reversed(before), *after]
        allowed = gatekeeper.visible_evidence_ids(db, p, project_id, [u.id for u in around])
        context = [_hit(u, u.text[:400]) for u in around if u.id in allowed]

    linked = _linked(db, p, project_id, unit)

    audit.record(db, actor_id=user.id, action="evidence.view", object_type="evidence", object_id=unit.id,
                 project_id=project_id)
    db.commit()
    hit = _hit(unit, "")
    return EvidenceDetail(
        **hit.model_dump(exclude={"snippet", "score"}),
        text=unit.text,
        source_name=source.name,
        source_kind=source.kind,
        redactions=[RedactionOut.model_validate(r) for r in redactions],
        label_reasons=unit.meta.get("label_reasons", []),
        meta={k: v for k, v in unit.meta.items() if k != "label_reasons"},
        context=context,
        linked=linked,
    )


@router.patch("/{evidence_id}", response_model=EvidenceDetail)
def relabel(
    project_id: uuid.UUID, evidence_id: uuid.UUID, body: EvidenceRelabel, p: ProjectPrincipal,
    user: CurrentUser, db: DB,
):
    require(policy.can_manage_project(p), "Only a project admin can change a label.")
    unit = _visible_unit(db, p, project_id, evidence_id)
    old = unit.sensitivity
    if old != body.sensitivity:
        unit.sensitivity = body.sensitivity
        unit.meta = {**unit.meta, "label_set_by": str(user.id)}
        audit.record(db, actor_id=user.id, action="evidence.relabel", object_type="evidence", object_id=unit.id,
                     project_id=project_id, old=old.value, new=body.sensitivity.value)
        db.commit()
        gatekeeper.relabel_evidence(db, unit, old)
    # The admin may have just labelled it beyond their own clearance.
    if evidence_id not in gatekeeper.visible_evidence_ids(db, p, project_id, [evidence_id]):
        raise HTTPException(404, "Relabelled. You're not cleared for that label, so it's now hidden from you.")
    return get_evidence(project_id, evidence_id, p, user, db)
