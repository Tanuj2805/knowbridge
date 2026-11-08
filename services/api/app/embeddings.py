"""Meaning-based search vectors. One interface, three providers:

  local   (default) a multilingual model run on this server with FastEmbed:
          nothing leaves the machine, no key needed
  gemini  Google's embedding API (better at romanised Hinglish)
  off     keyword search only (tests, or a team that wants no vectors)

Every vector is stored with the id of the model that made it. Vectors from
different models can't be compared, so search only uses vectors made by the
current model and `embed_missing` re-embeds the rest.
"""

import logging
import math
import os
import re
import threading
from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.db.models import EMBEDDING_DIM

log = logging.getLogger(__name__)
# Windows without developer mode can't symlink; the cache still works, the warning is noise.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# What gets fingerprinted. Bump RECIPE whenever text_for_embedding changes: it is
# part of every model id, so all items are re-embedded automatically.
RECIPE = "r2"

# Lines that describe *bookkeeping*, not the work: status, sprints, history.
# They stay in the stored evidence (agents and citations use them) but would
# drown the meaning of a short ticket if fingerprinted. Measured on a real Jira
# project: "Setup the dev environment" sat at distance 0.88 from "who set up the
# local environment" because 15 sprint names and history lines filled its text.
_BOOKKEEPING = re.compile(
    r"^(History:|\s+\d{1,2} \w{3} \d{4}\s|\s+… \d+ earlier|Sprint:|Story points:|Resolved:|Due:|Labels:|"
    r"Components:|Fix version:|Type:|State:|Status:|Branch:|Draft:|List:|Assigned to:|Reported by:|Unassigned|"
    r"Files touched:|First change:)"
)
_FILES = re.compile(r"^Files changed: (.*)$")


def text_for_embedding(title: str, text: str) -> str:
    """The meaningful part of an evidence item: title, description, discussion."""
    lines = []
    for line in text.split("\n"):
        if _BOOKKEEPING.match(line):
            continue
        m = _FILES.match(line)
        if m:  # a few paths say what was touched; fifty drown the message
            line = "Files changed: " + ", ".join(m.group(1).split(", ")[:8])
        lines.append(line)
    body = "\n".join(lines).strip()
    first = body.split("\n", 1)[0].strip()
    # Many items repeat their title as the first line; don't count it twice.
    return body if first and first in title or title in first else f"{title}\n{body}".strip()


# The local model reads ~128 tokens at a time; longer items are cut into
# overlapping windows and the window vectors are averaged.
CHUNK_CHARS = 500
CHUNK_OVERLAP = 100
MAX_CHUNKS = 8


# Calibrated on real data (Nimbus + a live Jira project): relevant matches 0.22–0.35,
# unrelated queries 0.40+. See docs/BUILD_PLAN.md decisions log.
GEMINI_MAX_DISTANCE = 0.37
# A keyword hit whose meaning is this far from the question is dropped (long tickets
# that merely contain "match" and "results"). Measured: right answers ≤ 0.43, wrong ≥ 0.44.
GEMINI_VETO_DISTANCE = 0.44
# Closer than this is shown as a "strong" match (top answers measured 0.22–0.33).
GEMINI_STRONG_DISTANCE = 0.33


class Embedder(Protocol):
    model_id: str
    external: bool  # True when text leaves this server (a third-party API)
    max_distance: float  # beyond this, a "nearest" match is unrelated
    veto_distance: float | None  # keyword hits further than this in meaning are dropped (None = no veto)
    strong_distance: float  # closer than this is labelled a strong match
    items_per_minute: int | None  # provider quota, None = unlimited

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _normalise(v) -> list[float]:
    n = math.sqrt(sum(float(x) * float(x) for x in v)) or 1.0
    return [float(x) / n for x in v]


def chunks(text: str) -> list[str]:
    """Overlapping windows, cut at whitespace where possible."""
    text = " ".join(text.split())
    if len(text) <= CHUNK_CHARS:
        return [text or " "]
    out, start = [], 0
    while start < len(text) and len(out) < MAX_CHUNKS:
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            space = text.rfind(" ", start + CHUNK_CHARS // 2, end)
            end = space if space > start else end
        out.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return out


def _mean(vectors: list[list[float]]) -> list[float]:
    return _normalise([sum(col) / len(vectors) for col in zip(*vectors, strict=True)])


class LocalEmbedder:
    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.model_id = f"local:{model_name}+{RECIPE}"
        self.external = False
        # Measured with this model on real data: relevant 0.40–0.59, unrelated 0.64+
        self.max_distance = 0.60
        # No veto: with this model right and wrong keyword hits overlap (0.61–0.88 vs 0.67–0.84).
        self.veto_distance: float | None = None
        self.strong_distance = 0.50
        self.items_per_minute: int | None = None  # no quota on our own server
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("loading local embedding model %s (first use downloads it)", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
        return self._model

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        out = [_normalise(v) for v in self._load().embed(texts, batch_size=32)]
        if out and len(out[0]) != EMBEDDING_DIM:
            raise RuntimeError(
                f"{self.model_name} makes {len(out[0])}-dim vectors; the database expects {EMBEDDING_DIM}"
            )
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        pieces: list[str] = []
        spans: list[tuple[int, int]] = []
        for t in texts:
            cs = chunks(t)
            spans.append((len(pieces), len(pieces) + len(cs)))
            pieces.extend(cs)
        vectors = self._vectors(pieces)
        return [_mean(vectors[a:b]) for a, b in spans]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors([text[:CHUNK_CHARS * 2]])[0]

    def warm_up(self) -> None:
        self._load()


class GeminiEmbedder:
    def __init__(self) -> None:
        s = get_settings()
        self.model_id = f"gemini:{s.gemini_embedding_model}@{s.embedding_dim}+{RECIPE}"
        self.external = True
        self.max_distance = GEMINI_MAX_DISTANCE
        self.veto_distance = GEMINI_VETO_DISTANCE
        self.strong_distance = GEMINI_STRONG_DISTANCE
        self.items_per_minute: int | None = s.embed_items_per_minute or None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from app.llm.embeddings import embed_documents

        return embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        from app.llm.embeddings import embed_query

        v = embed_query(text)
        if v is None:
            raise RuntimeError("Gemini embeddings unavailable")
        return v


@lru_cache
def embedder() -> Embedder | None:
    """The configured embedder, or None when meaning search is off or can't run."""
    s = get_settings()
    if s.embedding_provider == "off":
        return None
    if s.embedding_provider == "gemini":
        if not s.gemini_api_key:
            log.warning("EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is empty; search is keyword-only")
            return None
        return GeminiEmbedder()
    return LocalEmbedder(s.local_embedding_model, str(s.model_cache_dir))


_LABEL_ORDER = ["team", "restricted", "confidential"]


def sendable_labels(e: "Embedder") -> list[str]:
    """Labels whose text this embedder may receive."""
    if not e.external:
        return _LABEL_ORDER
    cap = get_settings().embed_external_max_label
    return _LABEL_ORDER[: _LABEL_ORDER.index(cap) + 1]


def current_model_id() -> str | None:
    e = embedder()
    return e.model_id if e else None


def embed_query(text: str) -> list[float] | None:
    """None when meaning search isn't available, so search falls back to keywords."""
    e = embedder()
    if e is None:
        return None
    try:
        return e.embed_query(text)
    except Exception as exc:  # a broken model must never break search
        log.warning("query embedding failed (%s); using keyword search only", exc)
        return None
