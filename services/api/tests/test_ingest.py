"""Ingests the whole Project Nimbus dataset and checks the traps planted in it."""

import uuid

import pytest
import yaml
from sqlalchemy import func, select

from app import demo, gatekeeper, ingest, retrieval, storage
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimType,
    EvidenceUnit,
    Project,
    Redaction,
    Sensitivity,
    Source,
    SourceStatus,
    User,
)
from tests.conftest import DATA

pytestmark = pytest.mark.db

SECRETS = ["N1mbus-Pg-2026", "Xk29fQpL7mWn4vRt8sYb", "Nimbus@2026"]
PII = ["98201 45567", "ishaan.rao@okaxis", "vikram.shah@zentrixlabs.in", "neha@printkaro.in"]


@pytest.fixture(scope="module")
def nimbus(database) -> uuid.UUID:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        project = demo.create_nimbus(db, enqueue=False)
        for source in db.scalars(select(Source).where(Source.project_id == project.id)).all():
            ingest.sync_source(db, source.id)
        return project.id


def _units(db, pid) -> list[EvidenceUnit]:
    return db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == pid)).all()


def _principal(db, pid, who: str):
    uid = db.scalar(select(User.id).where(User.email == f"{who}@nimbus.demo"))
    return gatekeeper.principal(db, pid, uid)


def test_every_source_is_ready(db, nimbus):
    sources = db.scalars(select(Source).where(Source.project_id == nimbus)).all()
    assert len(sources) == 7
    assert all(s.status == SourceStatus.ready for s in sources), [(s.name, s.status_detail) for s in sources]


def test_answer_key_phrases_exist(db, nimbus):
    """Every place the answer key points to must exist in the ingested evidence."""
    key = yaml.safe_load((DATA / "answer_key.yaml").read_text(encoding="utf-8"))
    names = {s.config.get("demo_key"): s.id
             for s in db.scalars(select(Source).where(Source.project_id == nimbus))}
    units = _units(db, nimbus)
    missing = []
    for section in ("decisions", "owners", "dependencies", "risks"):
        for item in key[section]:
            for src, phrase in item["in"]:
                if not any(u.source_id == names[src] and phrase.lower() in (u.title + u.text).lower()
                           for u in units):
                    missing.append((item["id"], src, phrase))
    for c in key["contradictions"]:
        for side in ("a", "b"):
            src, phrase = c[side]
            if not any(u.source_id == names[src] and phrase.lower() in (u.title + u.text).lower() for u in units):
                missing.append((c["id"], src, phrase))
    assert not missing, missing


def test_no_secret_or_personal_detail_survives(db, nimbus):
    blob = "\n".join(u.title + "\n" + u.text for u in _units(db, nimbus))
    for value in SECRETS + PII:
        assert value not in blob
    secrets = db.scalar(
        select(func.count()).select_from(Redaction).join(EvidenceUnit)
        .where(EvidenceUnit.project_id == nimbus, Redaction.category == "secret")
    )
    assert secrets >= 3


def test_confidential_items_are_labelled(db, nimbus):
    units = _units(db, nimbus)
    assert {u.sensitivity for u in units if "stipend" in u.text.lower()} == {Sensitivity.confidential}
    assert {u.sensitivity for u in units if "sick leave" in u.text} == {Sensitivity.confidential}


@pytest.mark.parametrize(
    ("who", "sees_confidential", "sees_committee"),
    [("meera", False, False), ("aarav", False, True), ("kabir", False, True), ("priya", True, True)],
)
def test_who_sees_what(db, nimbus, who, sees_confidential, sees_committee):
    p = _principal(db, nimbus, who)
    units = _units(db, nimbus)
    visible = gatekeeper.visible_evidence_ids(db, p, nimbus, [u.id for u in units])
    visible_q = retrieval.visible_units(p, nimbus, retrieval.Filters(include_removed=True)).subquery()
    sql_visible = set(db.scalars(select(visible_q.c.id)))
    assert visible == sql_visible
    confidential = {u.id for u in units if u.sensitivity == Sensitivity.confidential}
    committee_src = db.scalar(
        select(Source.id).where(Source.project_id == nimbus, Source.name == "Committee documents")
    )
    committee = {u.id for u in units if u.source_id == committee_src}
    assert bool(confidential & visible) is sees_confidential
    assert bool(committee & visible) is sees_committee


def test_prompt_injection_is_kept_as_plain_data(db, nimbus):
    hit = [u for u in _units(db, nimbus) if "ignore all previous instructions" in u.text]
    assert len(hit) == 1 and hit[0].kind == "message"


def test_hinglish_is_tagged(db, nimbus):
    langs = {u.language for u in _units(db, nimbus) if u.source_id in set(
        db.scalars(select(Source.id).where(Source.project_id == nimbus, Source.kind == "chat"))
    )}
    assert "hi-en" in langs


def test_keyword_search_finds_the_reason(db, nimbus):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, "why did we stop using webhooks",
                            query_vector=None)
    assert hits and hits[0].unit.locator == "PR #38"


@pytest.mark.parametrize(("query", "locator"), [("PR #42", "PR #42"), ("issue #40", "issue #40"),
                                               ("0b1c2d3", "0b1c2d3"), ("what happened in PR #38", "PR #38")])
def test_exact_ids_come_first(db, nimbus, query, locator):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, query, query_vector=None)
    assert hits and hits[0].unit.locator == locator


def test_an_id_alone_returns_only_that_item(db, nimbus):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, "PR #42", query_vector=None)
    assert [h.unit.locator for h in hits] == ["PR #42"]  # not every item that happens to contain "42"


def test_id_plus_words_searches_the_words_too(db, nimbus):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, "PR #42 reconciliation settlements",
                            query_vector=None)
    assert hits[0].unit.locator == "PR #42" and len(hits) > 1


def test_short_words_match_exactly_not_as_prefixes():
    assert retrieval._lexeme("up") == "up" and retrieval._lexeme("set") == "set"
    assert retrieval._lexeme("webhook") == "webhook:*"


def test_comments_are_grouped_under_their_pr(db, nimbus):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, "TICKET_SIGNING_SECRET rotate",
                            query_vector=None)
    pr21 = [h for h in hits if retrieval.group_key(h.unit) == ("pr", "PR #21")]
    assert len(pr21) == 1  # one result for PR #21, not one per comment
    assert pr21[0].unit.kind == "pull_request"  # the PR itself leads…
    assert {r.unit.kind for r in pr21[0].related} == {"pr_comment"}  # …with its matching comments under it


@pytest.mark.parametrize(("typo", "expect"), [("webhok", "webhook"), ("reconcilation", "reconciliation")])
def test_misspelt_words_still_match(db, nimbus, typo, expect):
    hits = retrieval.search(db, _principal(db, nimbus, "priya"), nimbus, typo, query_vector=None)
    assert hits and expect in (hits[0].unit.title + hits[0].unit.text).lower()


def test_real_words_are_not_treated_as_typos(db, nimbus):
    base = retrieval.visible_units(_principal(db, nimbus, "priya"), nimbus, retrieval.Filters())
    # words Nimbus uses are never "typos"; a misspelling of one is
    assert retrieval._probable_typos(db, base, ["webhooks", "registration", "reconcilation"]) == {"reconcilation"}


def test_search_never_returns_hidden_items(db, nimbus):
    hits = retrieval.search(db, _principal(db, nimbus, "meera"), nimbus, "stipend volunteers UPI", query_vector=None)
    assert all(h.unit.sensitivity != Sensitivity.confidential for h in hits)


def test_resync_is_idempotent(db, nimbus):
    source = db.scalar(select(Source).where(Source.project_id == nimbus, Source.kind == "taskboard"))
    report = ingest.sync_source(db, source.id)
    assert report.added == 0 and report.updated == 0 and report.unchanged == 20


def test_changed_source_flags_claims(db, nimbus):
    source = db.scalar(select(Source).where(Source.project_id == nimbus, Source.name == "Team meeting notes"))
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.source_id == source.id,
                                                EvidenceUnit.text.contains("every 60 seconds")))
    claim = Claim(project_id=nimbus, type=ClaimType.decision, statement="Payments are confirmed by polling.")
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(claim_id=claim.id, evidence_id=unit.id, quote="every 60 seconds", quote_hash="x"))
    db.commit()

    path = storage.source_dir(nimbus, source.id) / "2026-10-11-weekly-sync.md"
    path.write_text(path.read_text(encoding="utf-8").replace("every 60 seconds", "every 30 seconds"),
                    encoding="utf-8")
    report = ingest.sync_source(db, source.id)
    assert report.updated == 1
    db.refresh(claim)
    assert claim.source_changed is True


def test_removed_items_are_kept_and_flagged(db, nimbus):
    source = db.scalar(select(Source).where(Source.project_id == nimbus, Source.name == "WhatsApp: Nimbus Tech"))
    path = storage.list_files(nimbus, source.id)[0]
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:-1]), encoding="utf-8")
    report = ingest.sync_source(db, source.id)
    assert report.removed == 1
    removed = db.scalars(select(EvidenceUnit).where(EvidenceUnit.source_id == source.id,
                                                    EvidenceUnit.meta["removed_at"].astext.is_not(None))).all()
    assert len(removed) == 1


def teardown_module():
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        for p in db.scalars(select(Project).where(Project.name.like("Project Nimbus%"))).all():
            db.delete(p)
        db.commit()
