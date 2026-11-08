"""Smart search plumbing, with a small fake embedder so CI never downloads a model.

The fake turns words into a bag-of-words vector, so texts sharing words are
close and unrelated texts are far apart — enough to test the wiring:
chunking, model ids, re-embedding on model change, and the distance cut-off.
"""

import hashlib
import math
import uuid

import pytest
from sqlalchemy import select

from app import embeddings, ingest, retrieval
from app.db.models import EMBEDDING_DIM, EvidenceUnit, Membership, Project, Role, Source, SourceKind, User
from app.gatekeeper import principal


class FakeEmbedder:
    def __init__(self, model_id: str = "fake:v1", items_per_minute: int | None = None, fail_after: int | None = None):
        self.model_id = model_id
        self.external = False
        self.max_distance = 0.60
        self.veto_distance = None
        self.strong_distance = 0.30
        self.items_per_minute = items_per_minute
        self.fail_after = fail_after  # simulate the provider's quota running out mid-way
        self.calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        for w in text.lower().split():
            v[int(hashlib.sha256(w.strip(".,:").encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        from app.llm.embeddings import EmbeddingQuotaExceeded

        if self.fail_after is not None and self.calls >= self.fail_after:
            raise EmbeddingQuotaExceeded("429")
        self.calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


# --- chunking (no database) -----------------------------------------------


def test_short_text_is_one_chunk():
    assert embeddings.chunks("Payments use polling.") == ["Payments use polling."]


def test_long_text_is_split_with_overlap_and_a_cap():
    text = " ".join(f"word{i}" for i in range(2000))
    parts = embeddings.chunks(text)
    assert 1 < len(parts) <= embeddings.MAX_CHUNKS
    assert all(len(p) <= embeddings.CHUNK_CHARS for p in parts)
    assert parts[0].split()[-1] in parts[1]  # windows overlap, so no idea is cut in half


def test_bookkeeping_lines_are_not_fingerprinted():
    card = (
        "ROV-15: Setup the dev environment\n"
        "Type: Story · Status: In Review · Priority: Medium\n"
        "Assigned to: Rohan Das · Reported by: Ishita Rao\n"
        "Parent: ROV-18 Rover firmware\n"
        "Sprint: ROV Sprint 15 (active) · carried over through 15 sprints since ROV Sprint 1\n"
        "Story points: 4\n"
        "History:\n"
        "  03 Jun 2026  Rohan Das: status To Do → In Progress\n"
        "  … 3 earlier changes\n"
        "\n"
        "Install Docker and seed the local database."
    )
    out = embeddings.text_for_embedding("ROV-15: Setup the dev environment", card)
    assert "Setup the dev environment" in out and "Install Docker" in out and "Parent: ROV-18" in out
    for noise in ("Sprint", "Story points", "History", "Rohan Das: status", "Type:", "Assigned to"):
        assert noise not in out
    assert out.count("Setup the dev environment") == 1


def test_model_id_carries_the_recipe():
    e = embeddings.LocalEmbedder("some/model", ".models")
    assert e.model_id == f"local:some/model+{embeddings.RECIPE}"


def test_provider_off_means_keyword_only(monkeypatch):
    monkeypatch.setattr(embeddings, "embedder", lambda: None)
    assert embeddings.current_model_id() is None
    assert embeddings.embed_query("anything") is None


# --- through the database -------------------------------------------------


@pytest.fixture
def project(db):
    user = User(email=f"emb-{uuid.uuid4().hex[:6]}@test.dev", name="Tester")
    p = Project(name="Embeddings", slug=f"emb-{uuid.uuid4().hex[:8]}")
    db.add_all([user, p])
    db.flush()
    db.add(Membership(project_id=p.id, user_id=user.id, role=Role.admin))
    src = Source(project_id=p.id, kind=SourceKind.document, name="notes")
    db.add(src)
    db.flush()
    texts = {
        "e1": "Payments are confirmed by polling the orders API because webhooks failed on campus wifi",
        "e2": "The schedule comes from a Google Sheet the events committee edits",
        "e3": "Ticket QR codes carry signed tokens",
    }
    for ext, t in texts.items():
        db.add(EvidenceUnit(project_id=p.id, source_id=src.id, external_id=ext, kind="doc_section",
                            text=t, content_hash=ext))
    db.commit()
    return p, user


@pytest.mark.db
def test_embed_missing_records_the_model_and_skips_done_items(db, project, monkeypatch):
    p, _ = project
    fake = FakeEmbedder("fake:v1")
    monkeypatch.setattr(embeddings, "embedder", lambda: fake)
    assert ingest.embed_missing(db, project_id=p.id) == 3
    assert {u.embedding_model for u in db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == p.id))} == {
        "fake:v1"}
    assert ingest.embed_missing(db, project_id=p.id) == 0  # nothing left to do


@pytest.mark.db
def test_switching_models_re_embeds_everything(db, project, monkeypatch):
    p, _ = project
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:v1"))
    ingest.embed_missing(db, project_id=p.id)
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:v2"))
    assert ingest.embed_missing(db, project_id=p.id) == 3


@pytest.mark.db
def test_meaning_search_finds_items_and_ignores_other_models(db, project, monkeypatch):
    p, user = project
    fake = FakeEmbedder("fake:v1")
    monkeypatch.setattr(embeddings, "embedder", lambda: fake)
    ingest.embed_missing(db, project_id=p.id)
    who = principal(db, p.id, user.id)

    # Keyword and meaning search agree, so the right item ranks first
    hits = retrieval.search(db, who, p.id, "how are payments confirmed")
    assert hits and hits[0].unit.external_id == "e1"

    # Unrelated query: nothing within the distance cut-off, and no keyword hit
    assert retrieval.search(db, who, p.id, "zebra giraffe safari") == []

    # Vectors from another model are never compared with this one
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:v2"))
    assert retrieval.search(db, who, p.id, "how are payments confirmed", query_vector=fake.embed_query(
        "how are payments confirmed")) == retrieval.search(db, who, p.id, "how are payments confirmed",
                                                          query_vector=None)


@pytest.mark.db
def test_quota_embeds_one_portion_and_schedules_the_rest(db, project, monkeypatch):
    from datetime import UTC, datetime

    from app.db.models import Job, JobStatus

    p, _ = project
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:quota", items_per_minute=2))
    done, remaining = ingest.embed_with_quota(db, p.id)
    assert (done, remaining) == (2, 1)
    job = db.scalar(select(Job).where(Job.kind == "project.embed", Job.status == JobStatus.queued,
                                      Job.payload["project_id"].astext == str(p.id)))
    assert job is not None and job.run_after > datetime.now(UTC)  # resumes a minute later, worker stays free


@pytest.mark.db
def test_quota_running_out_keeps_what_was_done(db, project, monkeypatch):
    p, _ = project
    # 3 items in portions of 50 means one call; fail it: nothing done, no crash, nothing lost
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:fail", fail_after=0))
    assert ingest.embed_missing(db, project_id=p.id) == 0
    assert ingest.count_missing(db, p.id) == 3


@pytest.mark.db
def test_confidential_items_are_never_sent_to_an_external_provider(db, project, monkeypatch):
    from app.db.models import Sensitivity

    p, _ = project
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == p.id, EvidenceUnit.external_id == "e2"))
    unit.sensitivity = Sensitivity.confidential
    db.commit()

    sent: list[str] = []

    class External(FakeEmbedder):
        def embed_documents(self, texts):
            sent.extend(texts)
            return super().embed_documents(texts)

    ext = External("gemini:fake")
    ext.external = True
    monkeypatch.setattr(embeddings, "embedder", lambda: ext)
    assert ingest.embed_missing(db, project_id=p.id) == 2
    assert not any("Google Sheet" in t for t in sent)  # the confidential item's text never left
    assert ingest.count_missing(db, p.id) == 0  # and it isn't counted as "still to index"


@pytest.mark.db
def test_relabelled_items_lose_their_external_vector(db, project, monkeypatch):
    from app.db.models import Sensitivity

    p, _ = project
    ext = FakeEmbedder("gemini:fake")
    ext.external = True
    monkeypatch.setattr(embeddings, "embedder", lambda: ext)
    ingest.embed_missing(db, project_id=p.id)
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == p.id, EvidenceUnit.external_id == "e1"))
    unit.sensitivity = Sensitivity.confidential
    db.commit()
    ingest.embed_missing(db, project_id=p.id)
    db.refresh(unit)
    assert unit.embedding is None and unit.embedding_model is None


@pytest.mark.db
def test_a_local_provider_indexes_everything(db, project, monkeypatch):
    from app.db.models import Sensitivity

    p, _ = project
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == p.id, EvidenceUnit.external_id == "e3"))
    unit.sensitivity = Sensitivity.confidential
    db.commit()
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("local:fake"))  # external=False
    assert ingest.embed_missing(db, project_id=p.id) == 3


@pytest.mark.db
def test_meaning_veto_drops_keyword_hits_about_something_else(db, project, monkeypatch):
    p, user = project
    fake = FakeEmbedder("fake:veto")
    monkeypatch.setattr(embeddings, "embedder", lambda: fake)
    ingest.embed_missing(db, project_id=p.id)
    who = principal(db, p.id, user.id)
    q = "Google Sheet committee"  # a full keyword match on e2
    fake.max_distance = 0.0001  # isolate the keyword path: no meaning matches get added back

    assert [h.unit.external_id for h in retrieval.search(db, who, p.id, q)] == ["e2"]
    fake.veto_distance = 0.0001  # now every keyword hit counts as "about something else"
    assert retrieval.search(db, who, p.id, q) == []


@pytest.mark.db
def test_exact_ids_and_unvectored_items_are_never_vetoed(db, project, monkeypatch):
    from app.db.models import Sensitivity

    p, user = project
    fake = FakeEmbedder("gemini:fake")
    fake.external = True
    monkeypatch.setattr(embeddings, "embedder", lambda: fake)
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == p.id, EvidenceUnit.external_id == "e2"))
    unit.sensitivity = Sensitivity.confidential  # never sent out, so it has no vector
    membership = db.scalar(select(Membership).where(Membership.project_id == p.id, Membership.user_id == user.id))
    membership.clearances = ["confidential"]  # the reader may see it; the question is only the veto
    db.commit()
    ingest.embed_missing(db, project_id=p.id)
    fake.max_distance, fake.veto_distance = 0.0001, 0.0001
    hits = retrieval.search(db, principal(db, p.id, user.id), p.id, "Google Sheet committee")
    assert [h.unit.external_id for h in hits] == ["e2"]  # keyword-only, never vetoed


@pytest.mark.db
def test_thin_comments_cannot_match_on_their_issue_title(db, project, monkeypatch):
    p, user = project
    src = db.scalar(select(Source).where(Source.project_id == p.id))
    title = "Comment on ROV-85: Inconsistency in the mobile capture and web screenshot database"
    for ext, body in (("thin", "[attachment] After fix -"), ("real", "Mobile uploads use a different screenshot size")):
        db.add(EvidenceUnit(project_id=p.id, source_id=src.id, external_id=ext, kind="card_comment", title=title,
                            text=body, content_hash=ext))
    db.commit()
    monkeypatch.setattr(embeddings, "embedder", lambda: FakeEmbedder("fake:thin"))
    ingest.embed_missing(db, project_id=p.id)
    hits = retrieval.search(db, principal(db, p.id, user.id), p.id, "mobile web screenshot inconsistency")
    found = {h.unit.external_id for h in hits} | {r.unit.external_id for h in hits for r in h.related}
    assert "real" in found and "thin" not in found


@pytest.mark.db
def test_results_carry_a_strength(db, project, monkeypatch):
    p, user = project
    fake = FakeEmbedder("fake:strength")
    monkeypatch.setattr(embeddings, "embedder", lambda: fake)
    ingest.embed_missing(db, project_id=p.id)
    hits = retrieval.search(db, principal(db, p.id, user.id), p.id, "payments confirmed polling orders webhooks")
    assert hits[0].unit.external_id == "e1" and hits[0].strength == "strong"
