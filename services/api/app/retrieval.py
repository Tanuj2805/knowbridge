"""Hybrid search over evidence, filtered by the Gatekeeper *before* anything is
returned (and, from Phase 2, before anything reaches a model).

Steps: permission filter → exact IDs → keywords (with typo tolerance) → meaning
(vectors) → meaning veto on keyword hits → reciprocal-rank fusion → second
permission check (OpenFGA) → group comments under their issue/PR → label each
result "strong" or "possible".
"""

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, case, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app import embeddings, gatekeeper
from app.connectors.base import ISSUE_KEY
from app.db.models import EvidenceUnit, Sensitivity, Source
from app.gatekeeper.policy import Principal

RRF_K = 60
CANDIDATES = 60
RELATED_PER_RESULT = 5
# Typo tolerance (pg_trgm word similarity). Measured: "mimatch"→"mismatch" 0.55,
# "webhok"→"webhooks" 0.71. Only used for words that appear nowhere in the project.
TYPO_SIMILARITY = 0.5
TYPO_MIN_LENGTH = 5
# Comments inherit their issue's title. One whose own text is shorter than this
# ("[attachment] After fix -") can't match at all: it would only be matching the title.
# (Exact IDs still find it: "ROV-85" lists every comment.)
THIN_KINDS = ("card_comment", "pr_comment", "issue_comment", "pr_review")
THIN_CHARS = 30


@dataclass
class Filters:
    source_id: uuid.UUID | None = None
    kind: str | None = None
    sensitivity: Sensitivity | None = None
    language: str | None = None
    author: str | None = None
    include_removed: bool = False


@dataclass
class Hit:
    unit: EvidenceUnit
    score: float
    snippet: str
    strength: str = "possible"  # "strong" | "possible"
    distance: float | None = None
    related: list["Hit"] = field(default_factory=list)  # other matches in the same issue/PR/card


def visible_units(p: Principal, project_id: uuid.UUID, f: Filters) -> Select:
    q = (
        select(EvidenceUnit)
        .join(Source, Source.id == EvidenceUnit.source_id)
        .where(EvidenceUnit.project_id == project_id, gatekeeper.visible_evidence_clause(p))
    )
    if f.source_id:
        q = q.where(EvidenceUnit.source_id == f.source_id)
    if f.kind:
        q = q.where(EvidenceUnit.kind == f.kind)
    if f.sensitivity:
        q = q.where(EvidenceUnit.sensitivity == f.sensitivity)
    if f.language:
        q = q.where(EvidenceUnit.language == f.language)
    if f.author:
        q = q.where(EvidenceUnit.author.ilike(f"%{f.author}%"))
    if not f.include_removed:
        q = q.where(EvidenceUnit.meta["removed_at"].astext.is_(None))
    return q


# Question words carry no meaning for matching; dropping them lets any-word
# ranking surface the right passages ("why did we stop using webhooks").
_STOP = {
    "the", "and", "for", "are", "was", "were", "did", "does", "why", "what", "when", "who", "how", "which",
    "with", "that", "this", "from", "have", "has", "had", "our", "you", "your", "can", "should", "would",
    "about", "into", "using", "use", "used", "is", "it", "we", "do", "to", "of", "in", "on", "a", "an",
    "there", "here", "where", "some", "also", "very", "just", "they", "them", "then", "than", "been",
    # short words that, as prefixes, match half the dictionary ("not" -> notification, note)
    "not", "no", "all", "any", "but", "its", "out", "get", "got", "cant", "dont", "isnt",
}


def query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(t for t in re.findall(r"[^\W_]{2,}", query.lower()) if t not in _STOP))[:12]


def _lexeme(t: str) -> str:
    # Longer words match as prefixes (cheap stemming: 'webhook' finds 'webhooks'); short
    # ones only exactly, or 'up' would match 'update', 'upload', 'upgrade'…
    return f"{t}:*" if len(t) >= 4 else t


def _word_match(t: str, fuzzy: bool):
    exact = EvidenceUnit.tsv.op("@@")(func.to_tsquery("simple", _lexeme(t)))
    # `<%` is pg_trgm word similarity; uses the trigram index on evidence_units.text.
    return or_(exact, literal(t).op("<%")(EvidenceUnit.text)) if fuzzy else exact


def keyword_query(query: str):
    """OR of the meaningful words (no typo tolerance; used for keyword-only checks)."""
    terms = query_terms(query)
    if not terms:
        return None
    return func.to_tsquery("simple", " | ".join(_lexeme(t) for t in terms))


def _terms_matched(terms: list[str], typos: frozenset[str] = frozenset()):
    """SQL expression: how many of the query's words an item contains."""
    return sum((case((_word_match(t, t in typos), 1), else_=0) for t in terms), start=literal(0))


def _not_thin():
    own_text = func.length(func.btrim(func.regexp_replace(EvidenceUnit.text, r"\[attachment[^\]]*\]", "", "g")))
    return or_(EvidenceUnit.kind.not_in(THIN_KINDS), own_text >= THIN_CHARS)


def _probable_typos(db: Session, base: Select, terms: list[str]) -> frozenset[str]:
    """Longer words that appear nowhere the reader can see are probably misspelt."""
    out = set()
    for t in terms:
        if len(t) < TYPO_MIN_LENGTH:
            continue
        seen = db.execute(base.with_only_columns(literal(1)).where(_word_match(t, False)).limit(1)).first()
        if seen is None:
            out.add(t)
    return frozenset(out)


_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
_HASH_REF = re.compile(r"(?:PR|pr|issue|Issue)?\s*#(\d{1,6})\b")


def exact_refs(query: str) -> list[str]:
    """Identifiers a person types to jump to one item: ROV-15, a commit hash, PR #38."""
    refs = list(ISSUE_KEY.findall(query)) + [m[:7] for m in _SHA.findall(query.lower())]
    for n in _HASH_REF.findall(query):
        refs += [f"PR #{n}", f"issue #{n}"]
    return list(dict.fromkeys(refs))


def snippet(text: str, query: str, width: int = 220) -> str:
    terms = [t for t in re.findall(r"\w{3,}", query.lower())]
    lower = text.lower()
    hits = [i for t in terms if (i := lower.find(t)) >= 0]
    start = max(0, min(hits) - width // 3) if hits else 0
    out = text[start : start + width].strip()
    return ("…" if start > 0 else "") + out + ("…" if start + width < len(text) else "")


def group_key(u: EvidenceUnit) -> tuple[str, str]:
    """Comments and reviews belong with the issue, PR or card they're on."""
    m = u.meta or {}
    if m.get("provider") == "jira" and m.get("key"):
        return ("jira", m["key"])
    if u.kind == "pull_request":
        return ("pr", u.locator)
    if u.kind in ("pr_comment", "pr_review") and m.get("pr"):
        return ("pr", f"PR #{m['pr']}")
    if u.kind == "issue":
        return ("issue", u.locator)
    if u.kind == "issue_comment" and m.get("issue"):
        return ("issue", f"issue #{m['issue']}")
    if u.kind == "card" and u.external_id.startswith("trello:card:"):
        return ("trello", u.external_id.rsplit(":", 1)[-1])
    if u.kind == "card_comment" and m.get("card_id"):
        return ("trello", m["card_id"])
    if u.kind == "meeting_segment" and m.get("file"):
        return ("meeting", f"{u.source_id}:{m['file']}")
    return ("unit", str(u.id))


_PARENT_KINDS = ("card", "pull_request", "issue")


def _group(hits: list[Hit]) -> list[Hit]:
    """One result per issue/PR/card, in the order its best member ranked. The parent
    leads when it matched; other matches ride along in `related`."""
    groups: dict[tuple[str, str], list[Hit]] = {}
    for h in hits:
        groups.setdefault(group_key(h.unit), []).append(h)
    out = []
    for members in groups.values():
        head = next((h for h in members if h.unit.kind in _PARENT_KINDS), members[0])
        head.related = [h for h in members if h is not head][:RELATED_PER_RESULT]
        head.score = max(h.score for h in members)
        if any(h.strength == "strong" for h in members):
            head.strength = "strong"
        out.append(head)
    return out


def word_hits(terms: list[str], text: str) -> int:
    """How many of the query's words a text contains. Longer words also match other forms of
    themselves by their stem ('exceeds' finds 'excess', 'scores' finds 'score')."""
    words = set(re.findall(r"[^\W_]{2,}", text.lower()))
    hits = 0
    for t in terms:
        stem = t[: max(4, len(t) - 2)] if len(t) >= 5 else None
        if t in words or (stem and any(w.startswith(stem) for w in words)):
            hits += 1
    return hits


def search(
    db: Session,
    p: Principal,
    project_id: uuid.UUID,
    query: str,
    f: Filters | None = None,
    limit: int = 20,
    query_vector: list[float] | None | str = "auto",
) -> list[Hit]:
    """query_vector: "auto" embeds the query with the configured model;
    None means keyword search only. `limit` counts grouped results."""
    f = f or Filters()
    base = visible_units(p, project_id, f)
    ranks: dict[uuid.UUID, float] = {}
    units: dict[uuid.UUID, EvidenceUnit] = {}
    matched_words: dict[uuid.UUID, int] = {}
    distances: dict[uuid.UUID, float] = {}

    # IDs ("ROV-85", "PR #42", a commit hash) are looked up exactly and taken out of the
    # wording; otherwise "kct" + "85" would match every ticket in the project.
    refs = exact_refs(query)
    wording = _HASH_REF.sub(" ", _SHA.sub(" ", ISSUE_KEY.sub(" ", query)))
    terms = query_terms(wording)

    emb = embeddings.embedder()
    model_id = emb.model_id if emb else None
    if query_vector == "auto":
        query_vector = embeddings.embed_query(wording) if model_id and terms else None
    if refs and not terms:
        query_vector = None  # just an ID: nothing to search by meaning
    hybrid = model_id is not None and query_vector is not None

    # --- keywords (with typo tolerance for words found nowhere) ----------
    keyword: list[EvidenceUnit] = []
    if terms:
        typos = _probable_typos(db, base, terms)
        if typos:
            db.execute(text("select set_config('pg_trgm.word_similarity_threshold', :t, true)"),
                       {"t": str(TYPO_SIMILARITY)})
        tsq = func.to_tsquery("simple", " | ".join(_lexeme(t) for t in terms))
        any_word = or_(EvidenceUnit.tsv.op("@@")(tsq),
                       *[literal(t).op("<%")(EvidenceUnit.text) for t in typos])
        matched = _terms_matched(terms, typos).label("matched")
        q = base.add_columns(matched).where(any_word, _not_thin())
        if hybrid and len(terms) > 1:
            # Meaning search covers paraphrases, so a keyword hit must match most of the
            # question: "payment not working" shouldn't return everything with "working".
            q = q.where(_terms_matched(terms, typos) >= len(terms) // 2 + 1)
        # ts_rank_cd flag 1 divides by log(length): a long ticket doesn't win just by
        # containing many common words.
        rows = db.execute(
            q.order_by(matched.desc(), func.ts_rank_cd(EvidenceUnit.tsv, tsq, 1).desc()).limit(CANDIDATES)
        ).all()
        keyword = [u for u, _ in rows]
        matched_words = {u.id: m for u, m in rows}

    # --- meaning distances of keyword hits (veto + strength) -------------
    if keyword and hybrid:
        distances.update(db.execute(
            select(EvidenceUnit.id, EvidenceUnit.embedding.cosine_distance(query_vector)).where(
                EvidenceUnit.id.in_([u.id for u in keyword]), EvidenceUnit.embedding_model == model_id
            )
        ).all())
        veto = getattr(emb, "veto_distance", None)
        if veto:
            # Drop keyword hits clearly about something else. Items with no vector from this
            # model (e.g. Confidential, never sent out) are never vetoed.
            keyword = [u for u in keyword if distances.get(u.id, 0.0) <= veto]
    for rank, u in enumerate(keyword):
        units[u.id] = u
        ranks[u.id] = ranks.get(u.id, 0) + 1 / (RRF_K + rank)

    # --- meaning ---------------------------------------------------------
    if hybrid:
        distance = EvidenceUnit.embedding.cosine_distance(query_vector)
        rows = db.execute(
            base.add_columns(distance.label("d"))
            .where(EvidenceUnit.embedding.is_not(None), EvidenceUnit.embedding_model == model_id,
                   distance < emb.max_distance, _not_thin())
            .order_by(distance)
            .limit(CANDIDATES)
        ).all()
        for rank, (u, d) in enumerate(rows):
            units[u.id] = u
            distances[u.id] = d
            ranks[u.id] = ranks.get(u.id, 0) + 1 / (RRF_K + rank)

    # --- exact IDs -------------------------------------------------------
    exact_ids: set[uuid.UUID] = set()
    if refs:
        exact = db.scalars(
            base.where(or_(EvidenceUnit.locator.in_(refs), EvidenceUnit.meta["key"].astext.in_(refs)))
            .order_by(EvidenceUnit.kind)  # the issue/PR itself before its comments
            .limit(10)
        ).all()
        for n, u in enumerate(exact):
            units[u.id] = u
            exact_ids.add(u.id)
            ranks[u.id] = ranks.get(u.id, 0) + 1.0 - n * 0.01  # an exact ID beats any fuzzy match

    ordered = sorted(ranks, key=ranks.__getitem__, reverse=True)[: CANDIDATES]
    # Second opinion from the Gatekeeper backend (OpenFGA when enabled).
    allowed = gatekeeper.visible_evidence_ids(db, p, project_id, ordered)
    strong_distance = getattr(emb, "strong_distance", None)

    def strength(i: uuid.UUID) -> str:
        if i in exact_ids:
            return "strong"
        if strong_distance is not None and distances.get(i, 9.0) <= strong_distance:
            return "strong"
        if len(terms) >= 2 and matched_words.get(i, 0) == len(terms):
            return "strong"  # every meaningful word of the question is in it
        return "possible"

    hits = [
        Hit(unit=units[i], score=ranks[i], snippet=snippet(units[i].text, query), strength=strength(i),
            distance=distances.get(i))
        for i in ordered
        if i in allowed
    ]
    return _group(hits)[:limit]
