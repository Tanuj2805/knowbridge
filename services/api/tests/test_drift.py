"""Live sync and drift: a change at the source is checked by code first (are the quoted words still
there?), re-read by the Skeptic only when they aren't, and a claim whose support weakened goes back to
review; the published pack shows "changed since you read it"; the worker's schedule keeps live
sources fresh."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import demo, drift, gatekeeper, livesync
from app.agents.skeptic import Check, SkepticOut, Stance
from app.db.models import (
    Claim,
    ClaimDrift,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    ClaimVersion,
    EvidenceUnit,
    Grade,
    Handover,
    HandoverSection,
    HandoverStatus,
    Job,
    JobStatus,
    Run,
    RunStatus,
    Sensitivity,
    Source,
    SourceKind,
    SourceStatus,
    User,
)
from app.sentinel import content_hash

pytestmark = pytest.mark.db

TEXT = "Weekly sync. We agreed payments are confirmed by polling Razorpay every 60 seconds, since webhooks were flaky."


def _as(email: str):
    from tests.test_agents import _as as client

    return client(email)


def _uid(db, who: str) -> uuid.UUID:
    return db.scalar(select(User.id).where(User.email == f"{who}@nimbus.demo"))


@pytest.fixture(scope="module")
def project(database) -> uuid.UUID:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        p = demo.create_nimbus(db, enqueue=False)
        notes = Source(project_id=p.id, kind=SourceKind.document, name="Meeting notes", status=SourceStatus.ready)
        db.add(notes)
        db.flush()
        gatekeeper.sync_source(db, notes)
        db.add(Run(project_id=p.id, kind="reconstruct", status=RunStatus.done))
        db.commit()
        return p.id


@pytest.fixture
def setup(db, project):
    """A fresh item and an approved, Supported claim quoting it."""
    source = db.scalar(select(Source).where(Source.project_id == project, Source.name == "Meeting notes"))
    run = db.scalar(select(Run).where(Run.project_id == project))
    unit = EvidenceUnit(project_id=project, source_id=source.id, external_id=uuid.uuid4().hex, kind="doc_chunk",
                        title="Weekly sync", author="Aarav", text=TEXT, content_hash=content_hash(TEXT),
                        occurred_at=datetime.now(UTC), sensitivity=Sensitivity.team, meta={})
    db.add(unit)
    db.flush()
    gatekeeper.sync_evidence(db, [unit])
    claim = Claim(project_id=project, run_id=run.id, type=ClaimType.decision, subject="payment confirmation",
                  statement="Payments are confirmed by polling Razorpay every 60 seconds.", grade=Grade.supported,
                  grade_reason="Stated in one place.", status=ClaimStatus.approved, skeptic={"overreach": False})
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(claim_id=claim.id, evidence_id=unit.id, quote="polling Razorpay every 60 seconds",
                         quote_hash="x", stance="supports"))
    db.commit()
    return SimpleNamespace(source=source, unit=unit, claim=claim)


def _edit(db, unit: EvidenceUnit, text: str) -> str:
    old = f"{unit.title}\n{unit.text}"
    unit.text, unit.content_hash = text, content_hash(text)
    db.flush()
    return old


def _skeptic_says(monkeypatch, stance: str, note: str = ""):
    from app import llm
    from app.llm import gateway

    calls = []

    def fake(db, schema, **kw):
        calls.append(kw["prompt"])
        return SimpleNamespace(value=SkepticOut(checks=[Check(claim="C1", citations=[Stance(id="C1-E1", stance=stance)],
                                                              note=note)]))

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(gateway, "generate", fake)
    return calls


def _drifts(db, claim) -> list[ClaimDrift]:
    return db.scalars(select(ClaimDrift).where(ClaimDrift.claim_id == claim.id).order_by(ClaimDrift.detected_at)).all()


# --- the helpers -----------------------------------------------------------------------


def test_quote_check_ignores_case_and_spacing():
    assert drift.quote_present("polling  Razorpay\nevery 60 seconds", TEXT.upper())
    assert not drift.quote_present("every 60 seconds", TEXT.replace("60", "30"))
    assert not drift.quote_present("", TEXT)


def test_passages_show_the_same_stretch_before_and_after():
    before, after = drift.passages("every 60 seconds", TEXT, TEXT.replace("60", "30"))
    assert "every 60 seconds" in before and "every 30 seconds" in after
    assert drift.passages("every 60 seconds", TEXT, "")[1] == ""


# --- detecting -----------------------------------------------------------------------------


def test_an_edit_that_keeps_the_quote_costs_nothing(db, setup, monkeypatch):
    calls = _skeptic_says(monkeypatch, "supports")
    old = _edit(db, setup.unit, TEXT + " Also: the fest is on 14 Feb.")
    assert drift.detect(db, setup.source, [(setup.unit, old, False)], []) == 0
    db.commit()
    (d,) = _drifts(db, setup.claim)
    assert d.outcome == "quote_intact" and d.resolved_at is not None
    db.refresh(setup.claim)
    assert setup.claim.status == ClaimStatus.approved and setup.claim.source_changed is False
    assert drift.check_pending(db, setup.source.project_id) == 0 and calls == []  # no model call


def test_a_changed_quote_is_rechecked_and_a_contradiction_goes_back_to_review(db, setup, monkeypatch):
    old = _edit(db, setup.unit, TEXT.replace("every 60 seconds", "every 30 seconds"))
    assert drift.detect(db, setup.source, [(setup.unit, old, False)], []) == 1
    db.commit()
    db.refresh(setup.claim)
    assert setup.claim.source_changed is True and setup.claim.status == ClaimStatus.approved  # until re-read
    assert db.scalar(select(Job).where(Job.kind == "drift.check", Job.status == JobStatus.queued,
                                       Job.payload["project_id"].astext == str(setup.source.project_id)))

    calls = _skeptic_says(monkeypatch, "contradicts", "The notes now say every 30 seconds.")
    assert drift.check_pending(db, setup.source.project_id) == 1
    assert "every 30 seconds" in calls[0]  # the Skeptic read the new text
    db.refresh(setup.claim)
    assert setup.claim.status == ClaimStatus.draft and setup.claim.grade == Grade.conflicting
    assert setup.claim.review_note.startswith("Back for review: its source changed")
    (d,) = _drifts(db, setup.claim)
    assert (d.outcome, d.grade_before, d.grade_after, d.reopened) == ("contradicts", "supported", "conflicting", True)
    assert "every 60 seconds" in d.before and "every 30 seconds" in d.after
    assert db.scalar(select(ClaimVersion).where(ClaimVersion.claim_id == setup.claim.id)).status == ClaimStatus.approved


def test_a_reworded_item_that_still_backs_the_claim_stays_approved(db, setup, monkeypatch):
    old = _edit(db, setup.unit, TEXT.replace("polling Razorpay every 60 seconds", "polling Razorpay once a minute"))
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    _skeptic_says(monkeypatch, "supports")
    drift.check_pending(db, setup.source.project_id)
    db.refresh(setup.claim)
    assert setup.claim.status == ClaimStatus.approved and setup.claim.grade == Grade.supported
    assert setup.claim.source_changed is False
    (d,) = _drifts(db, setup.claim)
    assert d.outcome == "supports" and d.resolved_at is not None and not d.reopened


def test_a_deleted_item_never_removes_an_approved_claim_by_itself(db, setup, monkeypatch):
    calls = _skeptic_says(monkeypatch, "supports")
    assert drift.detect(db, setup.source, [], [setup.unit]) == 1
    db.commit()
    db.refresh(setup.claim)
    assert setup.claim.status == ClaimStatus.draft  # back to review, not rejected
    assert setup.claim.grade == Grade.inferred and "deleted" in setup.claim.grade_reason
    assert setup.claim.evidence[0].stance == "removed"
    assert _drifts(db, setup.claim)[0].outcome == "removed" and calls == []


def test_without_a_model_a_person_decides(db, setup, monkeypatch):
    from app import llm

    monkeypatch.setattr(llm, "configured", lambda: False)
    old = _edit(db, setup.unit, "Weekly sync. Payments: still being discussed.")
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    drift.check_pending(db, setup.source.project_id)
    db.refresh(setup.claim)
    assert _drifts(db, setup.claim)[0].outcome == "needs_person"
    assert setup.claim.status == ClaimStatus.draft and setup.claim.source_changed is True


def test_confidential_text_is_never_sent_for_a_recheck(db, setup, monkeypatch):
    calls = _skeptic_says(monkeypatch, "supports")
    setup.unit.sensitivity = Sensitivity.confidential
    old = _edit(db, setup.unit, TEXT.replace("60", "45"))
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    drift.check_pending(db, setup.source.project_id)
    assert calls == [] and _drifts(db, setup.claim)[0].outcome == "needs_person"


def test_undoing_a_change_is_checked_again(db, setup, monkeypatch):
    """After a re-judged change, the old words coming back isn't "nothing happened": the stance on
    record came from the change, so the Skeptic looks again."""
    old = _edit(db, setup.unit, TEXT.replace("60", "30"))
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    _skeptic_says(monkeypatch, "contradicts")
    drift.check_pending(db, setup.source.project_id)
    old = _edit(db, setup.unit, TEXT)
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    assert _drifts(db, setup.claim)[-1].outcome == "pending"
    _skeptic_says(monkeypatch, "supports")
    drift.check_pending(db, setup.source.project_id)
    db.refresh(setup.claim)
    assert setup.claim.grade == Grade.supported and setup.claim.status == ClaimStatus.draft  # still a person's call


# --- a real sync -----------------------------------------------------------------------------


def test_a_resync_runs_the_drift_check(db, project, monkeypatch):
    """The meeting notes file changes on disk; the sync sees it and flags only the claim it matters to."""
    from app import ingest, storage

    source = Source(project_id=project, kind=SourceKind.document, name="Notes upload", status=SourceStatus.ready)
    db.add(source)
    db.flush()
    gatekeeper.sync_source(db, source)
    storage.save_upload(project, source.id, "sync.md", f"# Weekly sync\n\n{TEXT}\n".encode())
    source.config = {"files": ["sync.md"]}
    db.commit()
    ingest.sync_source(db, source.id)
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.source_id == source.id))
    claim = Claim(project_id=project, run_id=db.scalar(select(Run.id).where(Run.project_id == project)),
                  type=ClaimType.decision, statement="Payments are polled every 60 seconds.", grade=Grade.supported,
                  status=ClaimStatus.approved, skeptic={"overreach": False})
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(claim_id=claim.id, evidence_id=unit.id, quote="every 60 seconds", quote_hash="x",
                         stance="supports"))
    db.commit()

    storage.save_upload(project, source.id, "sync.md", f"# Weekly sync\n\n{TEXT.replace('60', '30')}\n".encode())
    report = ingest.sync_source(db, source.id)
    assert report.updated == 1 and report.drifted == 1
    assert "1 claim cites something that changed" in db.get(Source, source.id).status_detail
    db.refresh(claim)
    assert claim.source_changed is True and _drifts(db, claim)[0].outcome == "pending"


# --- what people see ----------------------------------------------------------------------------


def test_the_ledger_lists_changed_claims_and_a_review_settles_them(db, setup, monkeypatch):
    old = _edit(db, setup.unit, TEXT.replace("60", "30"))
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    _skeptic_says(monkeypatch, "contradicts", "Now every 30 seconds.")
    drift.check_pending(db, setup.source.project_id)

    priya = _as("priya@nimbus.demo")
    pid = setup.source.project_id
    page = priya.get(f"/projects/{pid}/claims", params={"review": "changed"}).json()
    assert page["review"]["changed"] >= 1
    item = next(i for i in page["items"] if i["id"] == str(setup.claim.id))
    assert item["source_changed"] is True
    assert item["drift"]["outcome"] == "contradicts" and "every 30 seconds" in item["drift"]["after"]

    log = priya.get(f"/projects/{pid}/drift").json()
    assert any(d["claim_id"] == str(setup.claim.id) and d["reopened"] for d in log["items"])
    assert log["sync_every_hours"] == 6.0

    assert priya.patch(f"/projects/{pid}/claims/{setup.claim.id}", json={"action": "approve"}).status_code == 204
    db.expire_all()
    assert db.get(Claim, setup.claim.id).source_changed is False
    d = _drifts(db, setup.claim)[0]
    assert d.resolved_at is not None and d.resolved_by == _uid(db, "priya")


def test_the_drift_log_is_for_staff(project):
    assert _as("meera@nimbus.demo").get(f"/projects/{project}/drift").status_code == 403


def test_the_published_pack_says_what_changed_since_it_was_read(db, setup, monkeypatch):
    pid = setup.source.project_id
    h = Handover(project_id=pid, title="Aarav to Meera", leaver_id=_uid(db, "aarav"), successor_id=_uid(db, "meera"),
                 approver_id=_uid(db, "priya"), status=HandoverStatus.published, version=1)
    db.add(h)
    db.flush()
    sec = HandoverSection(handover_id=h.id, recipient_id=h.successor_id, version=1, key="decisions", position=1,
                          title="Decisions", content={"intro": "", "blocks": [{
                              "claim_id": str(setup.claim.id), "type": "decision", "statement": setup.claim.statement,
                              "rationale": "", "grade": "supported", "grade_reason": "", "owner": "", "due": None,
                              "since": None, "history": [], "cites": []}]})
    db.add(sec)
    db.commit()
    # the database's clock, like the change's own time: the computer's clock can drift from Docker's
    sec.acknowledged_at = db.scalar(select(func.now()))
    db.commit()

    old = _edit(db, setup.unit, TEXT.replace("60", "30"))
    drift.detect(db, setup.source, [(setup.unit, old, False)], [])
    db.commit()
    _skeptic_says(monkeypatch, "contradicts")
    drift.check_pending(db, pid)

    pack = _as("meera@nimbus.demo").get(f"/projects/{pid}/handovers/{h.id}/pack").json()
    block = pack["sections"][0]["blocks"][0]
    assert block["changed"]["since_read"] is True and block["changed"]["in_review"] is True
    assert block["statement"] == setup.claim.statement  # the snapshot itself never changes
    detail = _as("priya@nimbus.demo").get(f"/projects/{pid}/handovers/{h.id}").json()
    assert detail["pack_changed"] == 1


# --- demo mode: simulate a change ------------------------------------------------------------------


def test_an_admin_can_simulate_a_source_change_in_demo_mode(db, setup, monkeypatch):
    _skeptic_says(monkeypatch, "contradicts")
    pid, url = setup.source.project_id, f"/projects/{setup.source.project_id}/evidence/{setup.unit.id}/simulate-change"
    changed = TEXT.replace("60 seconds", "30 seconds") + " Contact aarav@example.com."
    assert _as("priya@nimbus.demo").post(url, json={"text": changed}).status_code == 403  # approver, not admin
    assert _as("kabir@nimbus.demo").post(url, json={"text": TEXT}).status_code == 422  # nothing changed
    r = _as("kabir@nimbus.demo").post(url, json={"text": changed})
    assert r.status_code == 200 and r.json() == {"claims": 1}
    db.expire_all()
    unit = db.get(EvidenceUnit, setup.unit.id)
    assert "aarav@example.com" not in unit.text  # Sentinel masks the new words too
    d = _drifts(db, setup.claim)[0]
    assert d.simulated and d.outcome == "pending"
    drift.check_pending(db, pid)
    assert db.get(Claim, setup.claim.id).status == ClaimStatus.draft


def test_simulating_is_off_outside_demo_mode(setup, monkeypatch):
    from app.routers import drift as drift_router

    # only the endpoint's view of the setting: demo sign-in itself needs demo mode
    monkeypatch.setattr(drift_router, "get_settings", lambda: SimpleNamespace(demo_mode=False, live_sync_hours=6.0))
    url = f"/projects/{setup.source.project_id}/evidence/{setup.unit.id}/simulate-change"
    assert _as("kabir@nimbus.demo").post(url, json={"text": "changed"}).status_code == 404


# --- the schedule ---------------------------------------------------------------------------------


def test_the_schedule_queues_live_sources_that_are_due(db, project, monkeypatch):
    now = datetime.now(UTC)
    old, fresh, upload, broken = (
        Source(project_id=project, kind=SourceKind.github, name="old repo", status=SourceStatus.ready,
               config={"repo": "a/old"}, last_synced_at=now - timedelta(hours=7)),
        Source(project_id=project, kind=SourceKind.github, name="fresh repo", status=SourceStatus.ready,
               config={"repo": "a/fresh", "last_full_sync_at": now.isoformat()},
               last_synced_at=now - timedelta(hours=1)),
        Source(project_id=project, kind=SourceKind.document, name="old upload", status=SourceStatus.ready,
               last_synced_at=now - timedelta(days=3)),
        Source(project_id=project, kind=SourceKind.taskboard, name="broken jira", status=SourceStatus.failed,
               config={"provider": "jira"}, last_synced_at=now - timedelta(days=3)),
    )
    db.add_all([old, fresh, upload, broken])
    db.commit()

    def queued(s: Source):
        return db.scalars(select(Job).where(Job.kind == "source.sync", Job.status == JobStatus.queued,
                                            Job.payload["source_id"].astext == str(s.id))).all()

    livesync.schedule_due(db, now)
    (job,) = queued(old)
    assert job.payload.get("full") is True and job.payload.get("scheduled") is True  # never had a full read
    assert db.get(Source, old.id).status == SourceStatus.pending
    assert not queued(fresh) and not queued(upload) and not queued(broken)
    assert livesync.next_check(fresh) == fresh.last_synced_at + timedelta(hours=6)
    assert livesync.next_check(upload) is None

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "live_sync_hours", 0)
    fresh.last_synced_at = now - timedelta(days=1)
    db.commit()
    assert livesync.schedule_due(db, now) == 0
