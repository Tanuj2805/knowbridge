"""Connect step: Scout reads a source, Sentinel redacts and labels every item,
and the result is stored as Evidence Units with their access rules.

Re-syncing is safe: unchanged items are skipped, changed items are updated and
any claim citing them is flagged "source changed", and items that disappeared
are kept but marked removed (claims citing them are flagged too).
"""

import logging
import uuid
from datetime import UTC, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import embeddings, gatekeeper, lang, secretbox, storage
from app.config import get_settings
from app.connectors import ISSUE_KEY, ConnectorError, RawItem, RetryLater, is_live, read_source
from app.db.models import (
    Claim,
    ClaimEvidence,
    EvidenceUnit,
    Redaction,
    Sensitivity,
    Source,
    SourceStatus,
)
from app.sentinel import content_hash, scan, strictest

log = logging.getLogger(__name__)

MAX_ITEM_CHARS = 20_000
IST = timezone(timedelta(hours=5, minutes=30))


class SyncReport:
    def __init__(self) -> None:
        self.added = self.updated = self.unchanged = self.removed = self.skipped = 0
        self.secrets = self.pii = 0
        self.embedded = 0

    def summary(self) -> str:
        parts = [f"{self.added} new", f"{self.updated} changed", f"{self.unchanged} unchanged"]
        if self.removed:
            parts.append(f"{self.removed} gone from the source")
        if self.skipped:
            parts.append(f"{self.skipped} outside the date range")
        masked = []
        if self.secrets:
            masked.append(f"{self.secrets} secret{'s' if self.secrets != 1 else ''}")
        if self.pii:
            masked.append(f"{self.pii} personal detail{'s' if self.pii != 1 else ''}")
        text = ", ".join(parts) + "."
        if masked:
            text += " Masked " + " and ".join(masked) + "."
        return text


def _in_scope(item: RawItem, source: Source) -> bool:
    if item.occurred_at is None:
        return True
    if source.scope_from and item.occurred_at < datetime.combine(source.scope_from, time.min, UTC):
        return False
    if source.scope_to and item.occurred_at > datetime.combine(source.scope_to, time.max, UTC):
        return False
    return True


def _hint(value: str | None) -> Sensitivity:
    try:
        return Sensitivity(value) if value else Sensitivity.team
    except ValueError:
        return Sensitivity.team


def _flag_claims(db: Session, evidence_ids: list[uuid.UUID]) -> None:
    if not evidence_ids:
        return
    claim_ids = select(ClaimEvidence.claim_id).where(ClaimEvidence.evidence_id.in_(evidence_ids))
    db.execute(update(Claim).where(Claim.id.in_(claim_ids)).values(source_changed=True))


def sync_source(db: Session, source_id: uuid.UUID, full: bool = False) -> SyncReport:
    """full=False lets live sources fetch only what changed since the last sync."""
    source = db.get(Source, source_id)
    if source is None:
        raise ValueError(f"source {source_id} not found")
    source.status = SourceStatus.syncing
    source.status_detail = "Reading…"
    db.commit()

    report = SyncReport()
    try:
        _sync(db, source, report, full)
    except RetryLater as e:
        db.rollback()
        source = db.get(Source, source_id)
        source.status = SourceStatus.pending
        at = e.retry_at.astimezone(IST).strftime("%H:%M")
        source.status_detail = f"Paused: {e} Continuing automatically at {at}."
        db.commit()
        raise
    except ConnectorError as e:
        db.rollback()
        source = db.get(Source, source_id)
        source.status = SourceStatus.failed
        source.status_detail = str(e)
        db.commit()
        raise
    except Exception:
        db.rollback()
        source = db.get(Source, source_id)
        source.status = SourceStatus.failed
        source.status_detail = "Something went wrong while reading this source. It will be retried."
        db.commit()
        raise
    return report


def _sync(db: Session, source: Source, report: SyncReport, full: bool) -> None:
    s = get_settings()
    since = datetime.combine(source.scope_from, time.min, UTC) if source.scope_from else None
    live = is_live(source.kind, source.config or {})
    # A day of overlap covers clock skew and items edited mid-sync.
    incremental = live and not full and source.last_synced_at is not None
    changed_since = source.last_synced_at - timedelta(days=1) if incremental else None
    try:
        secret = secretbox.unseal(source.secret) if source.secret else None
    except secretbox.SecretUnreadable as e:
        raise ConnectorError(str(e)) from e
    items = read_source(
        source.kind,
        source.config or {},
        storage.list_files(source.project_id, source.id),
        github_token=s.github_token,
        since=since,
        secret=secret,
        changed_since=changed_since,
        workdir=storage.source_dir(source.project_id, source.id) / "repo.git",
    )

    existing = {
        u.external_id: u
        for u in db.scalars(select(EvidenceUnit).where(EvidenceUnit.source_id == source.id))
    }
    seen: set[str] = set()
    new_units: list[EvidenceUnit] = []
    relabelled: list[tuple[EvidenceUnit, Sensitivity]] = []
    changed_ids: list[uuid.UUID] = []

    for item in items:
        if item.external_id in seen:
            continue
        seen.add(item.external_id)
        if not _in_scope(item, source):
            report.skipped += 1
            continue

        floor = strictest(source.default_sensitivity, _hint(item.sensitivity_hint))
        body = scan(item.text[:MAX_ITEM_CHARS], floor=floor)
        title = scan(item.title, floor=floor)
        sensitivity = strictest(body.sensitivity, title.sensitivity)
        report.secrets += body.secret_count + title.secret_count
        report.pii += len(body.findings) + len(title.findings) - body.secret_count - title.secret_count
        digest = content_hash(title.text + "\n" + body.text)

        unit = existing.get(item.external_id)
        if unit is not None and unit.content_hash == digest and not unit.meta.get("removed_at"):
            if unit.sensitivity != sensitivity:
                relabelled.append((unit, unit.sensitivity))
                unit.sensitivity = sensitivity
            report.unchanged += 1
            continue

        meta = dict(item.meta)
        refs = sorted(set(ISSUE_KEY.findall(f"{title.text}\n{body.text}")) - {meta.get("key")})
        if refs:
            meta["refs"] = refs[:20]
        if body.sensitivity_reasons:
            meta["label_reasons"] = body.sensitivity_reasons[:5]
        if unit is None:
            unit = EvidenceUnit(project_id=source.project_id, source_id=source.id, external_id=item.external_id)
            db.add(unit)
            new_units.append(unit)
            report.added += 1
        else:
            changed_ids.append(unit.id)
            if unit.sensitivity != sensitivity:
                relabelled.append((unit, unit.sensitivity))
            db.query(Redaction).filter(Redaction.evidence_id == unit.id).delete()
            unit.embedding = None
            report.updated += 1

        unit.kind = item.kind
        unit.title = title.text[:500]
        unit.text = body.text
        unit.author = item.author[:200]
        unit.occurred_at = item.occurred_at
        unit.permalink = item.permalink[:1000]
        unit.locator = item.locator[:200]
        unit.content_hash = digest
        unit.sensitivity = sensitivity
        unit.language = lang.detect(body.text)
        unit.meta = meta
        db.flush()
        for finding, start, end in body.placeholders:
            db.add(Redaction(evidence_id=unit.id, rule_id=finding.rule_id, category=finding.category,
                             start=start, end=end))

    # An incremental sync only sees what changed, so it can't tell what was deleted.
    gone = [] if incremental else [
        u for ext, u in existing.items() if ext not in seen and not u.meta.get("removed_at")
    ]
    for u in gone:
        u.meta = {**u.meta, "removed_at": datetime.now(UTC).isoformat()}
        changed_ids.append(u.id)
    report.removed = len(gone)
    _flag_claims(db, changed_ids)

    source.status_detail = "Indexing…"
    db.commit()

    embed_note = ""
    try:
        report.embedded, waiting = embed_with_quota(db, source.project_id, source.id)
        if waiting:
            embed_note = f" Smart search: {waiting} items still being indexed (within the provider's per-minute quota)."
    except Exception as e:  # evidence is stored; vectors can be filled in later
        db.rollback()
        log.warning("embedding failed for source %s: %s", source.id, e)
        embed_note = " Smart search isn't ready for these items yet (embedding failed); keyword search works."

    gatekeeper.sync_source(db, source)
    gatekeeper.sync_evidence(db, new_units)
    for unit, old in relabelled:
        gatekeeper.relabel_evidence(db, unit, old)

    source.status = SourceStatus.ready
    source.item_count = db.scalar(
        select(func.count()).select_from(EvidenceUnit).where(
            EvidenceUnit.source_id == source.id, EvidenceUnit.meta["removed_at"].astext.is_(None)
        )
    ) or 0
    source.last_synced_at = datetime.now(UTC)
    source.status_detail = ("Checked for changes: " if incremental else "") + report.summary() + embed_note
    if embeddings.embedder() is None:
        source.status_detail += " Smart search is off, so search is keyword-only."
    db.commit()
    log.info("synced source %s: %s", source.id, source.status_detail)


def _missing(e, source_id: uuid.UUID | None, project_id: uuid.UUID | None):
    stale = or_(EvidenceUnit.embedding.is_(None), EvidenceUnit.embedding_model.is_distinct_from(e.model_id))
    q = select(EvidenceUnit.id).where(stale, EvidenceUnit.sensitivity.in_(embeddings.sendable_labels(e)))
    if source_id:
        q = q.where(EvidenceUnit.source_id == source_id)
    if project_id:
        q = q.where(EvidenceUnit.project_id == project_id)
    return q


def _forget_unsendable(db: Session, e, source_id: uuid.UUID | None, project_id: uuid.UUID | None) -> None:
    """Items labelled above what an external provider may see (e.g. relabelled to
    Confidential later) lose their externally made vector; they stay keyword-only."""
    if not e.external:
        return
    q = update(EvidenceUnit).where(
        EvidenceUnit.embedding_model.like("gemini:%"),
        EvidenceUnit.sensitivity.not_in(embeddings.sendable_labels(e)),
    )
    if source_id:
        q = q.where(EvidenceUnit.source_id == source_id)
    if project_id:
        q = q.where(EvidenceUnit.project_id == project_id)
    if db.execute(q.values(embedding=None, embedding_model=None)).rowcount:
        db.commit()


def count_missing(db: Session, project_id: uuid.UUID) -> int:
    e = embeddings.embedder()
    if e is None:
        return 0
    return db.scalar(select(func.count()).select_from(_missing(e, None, project_id).subquery())) or 0


def embed_missing(
    db: Session,
    source_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    max_items: int | None = None,
) -> int:
    """Embed units with no vector, or a vector from a different model, up to
    `max_items` (the provider's per-minute quota). Stops early, keeping what's
    done, if the quota runs out. Returns how many were embedded."""
    from app.llm.embeddings import EmbeddingQuotaExceeded

    e = embeddings.embedder()
    if e is None:
        return 0
    _forget_unsendable(db, e, source_id, project_id)
    q = _missing(e, source_id, project_id)
    if max_items:
        q = q.limit(max_items)
    ids = db.scalars(q).all()
    done = 0
    for i in range(0, len(ids), 50):
        batch = db.scalars(select(EvidenceUnit).where(EvidenceUnit.id.in_(ids[i : i + 50]))).all()
        try:
            vectors = e.embed_documents([embeddings.text_for_embedding(u.title, u.text) for u in batch])
        except EmbeddingQuotaExceeded:
            log.info("embedding quota reached after %s items; resuming in a minute", done)
            break
        for u, v in zip(batch, vectors, strict=True):
            u.embedding = v
            u.embedding_model = e.model_id
        db.commit()
        done += len(batch)
    return done


def embed_with_quota(db: Session, project_id: uuid.UUID, source_id: uuid.UUID | None = None) -> tuple[int, int]:
    """One quota-sized portion now; if items remain, a job finishes them a minute
    later (so a big project never blocks the worker). Returns (done, remaining)."""
    from app import jobs

    e = embeddings.embedder()
    if e is None:
        return 0, 0
    done = embed_missing(db, source_id=source_id, project_id=project_id, max_items=e.items_per_minute)
    remaining = count_missing(db, project_id)
    if remaining:
        jobs.enqueue(db, "project.embed", {"project_id": project_id},
                     run_after=datetime.now(UTC) + timedelta(seconds=61))
        db.commit()
    return done, remaining
