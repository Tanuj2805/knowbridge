"""Search quality with the REAL local embedding model on Project Nimbus.

Runs when the model is available: set KB_REAL_MODEL=1 (CI does, with the model
cached between runs), or have it already downloaded in MODEL_CACHE_DIR.
Each query is phrased differently from the evidence it should find.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app import demo, embeddings, gatekeeper, ingest, retrieval
from app.config import get_settings
from app.db.models import Project, Source, User

MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def _model_available() -> bool:
    try:
        import fastembed  # noqa: F401  (optional: pip install .[local-search])
    except ImportError:
        return False
    if os.environ.get("KB_REAL_MODEL") == "1":
        return True
    cache = Path(get_settings().model_cache_dir)
    return cache.exists() and any(cache.glob("*paraphrase-multilingual-mpnet-base-v2*"))


pytestmark = [
    pytest.mark.db,
    pytest.mark.model,
    pytest.mark.skipif(not _model_available(), reason="real embedding model not downloaded (set KB_REAL_MODEL=1)"),
]

# (query, phrases that the right evidence contains)
PARAPHRASED = [
    ("why did we stop relying on payment callbacks", ["webhook", "polling"]),
    ("the server was asleep and slow at the gate", ["cold start", "Render"]),
    ("who takes care of renewing the website address", ["renew", "domain"]),
    ("iPhone users not getting alerts", ["iOS", "push"]),
    ("scanner breaks on older phones", ["Android 9", "old Android"]),
    ("fest ki dates kab hai", ["23-25 Jan", "16–18 January"]),
    ("people getting charged twice", ["Duplicate", "duplicate"]),
]


@pytest.fixture(scope="module")
def nimbus_with_vectors(database):
    from app.db.session import SessionLocal

    real = embeddings.LocalEmbedder(MODEL, str(get_settings().model_cache_dir))
    with SessionLocal() as db:
        project = demo.create_nimbus(db, enqueue=False)
        for source in db.scalars(select(Source).where(Source.project_id == project.id)).all():
            ingest.sync_source(db, source.id)
        original = embeddings.embedder
        embeddings.embedder = lambda: real
        try:
            assert ingest.embed_missing(db, project_id=project.id) > 100
        finally:
            embeddings.embedder = original
        yield project.id, real
        db.delete(db.get(Project, project.id))
        db.commit()


def _priya(db, pid):
    return gatekeeper.principal(db, pid, db.scalar(select(User.id).where(User.email == "priya@nimbus.demo")))


@pytest.mark.parametrize(("query", "needles"), PARAPHRASED)
def test_paraphrased_questions_find_the_right_evidence(db, nimbus_with_vectors, monkeypatch, query, needles):
    pid, real = nimbus_with_vectors
    monkeypatch.setattr(embeddings, "embedder", lambda: real)
    hits = retrieval.search(db, _priya(db, pid), pid, query, limit=5)
    assert any(any(n in h.unit.title + h.unit.text for n in needles) for h in hits), [h.unit.locator for h in hits]


def test_meaning_search_beats_keywords_on_reworded_question(db, nimbus_with_vectors, monkeypatch):
    """No word of the query appears in the Render cold-start message; only meaning finds it."""
    pid, real = nimbus_with_vectors
    monkeypatch.setattr(embeddings, "embedder", lambda: real)
    q = "the server was asleep and slow at the gate"
    keyword = retrieval.search(db, _priya(db, pid), pid, q, query_vector=None, limit=5)
    hybrid = retrieval.search(db, _priya(db, pid), pid, q, limit=5)
    hit = lambda hs: any("cold start" in h.unit.text or "Render" in h.unit.text for h in hs)  # noqa: E731
    assert not hit(keyword) and hit(hybrid)


def test_hidden_items_never_come_back_through_meaning_search(db, nimbus_with_vectors, monkeypatch):
    pid, real = nimbus_with_vectors
    monkeypatch.setattr(embeddings, "embedder", lambda: real)
    meera = gatekeeper.principal(db, pid, db.scalar(select(User.id).where(User.email == "meera@nimbus.demo")))
    hits = retrieval.search(db, meera, pid, "volunteer payment amounts and health leave", limit=20)
    assert not any("stipend" in h.unit.text.lower() or "sick leave" in h.unit.text for h in hits)


@pytest.mark.parametrize(
    "query", ["quantum physics lecture", "recipe for paneer butter masala", "football match results"]
)
def test_unrelated_questions_get_no_meaning_matches(db, nimbus_with_vectors, query):
    """Vector search always has a nearest item; the distance cut-off must drop it.
    (Keyword hits are a separate matter: "match" legitimately matches "match them".)"""
    from app.db.models import EvidenceUnit

    pid, real = nimbus_with_vectors
    distance = EvidenceUnit.embedding.cosine_distance(real.embed_query(query))
    close = db.scalars(
        select(EvidenceUnit.id).where(EvidenceUnit.project_id == pid, EvidenceUnit.embedding_model == real.model_id,
                                      distance < real.max_distance)
    ).all()
    assert close == []
