"""Gemini embeddings (multilingual, so Hinglish chat lands near English text).

Called over REST, not through the SDK: the SDK takes minutes to report a full quota that the API
reports in half a second, and a search can't wait. Each call tries the key in use, then the
backup keys (app.llm.with_failover)."""

import logging
import math
from functools import lru_cache

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.llm import KeyUnavailable, LLMUnavailable, http_transport, with_failover

log = logging.getLogger(__name__)

BATCH = 50
MAX_CHARS = 7000  # gemini-embedding-001 reads ~2k tokens; keep well inside
QUERY_TIMEOUT = 8.0  # seconds a search waits for its question's vector
DOCUMENT_TIMEOUT = 60.0
API = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingQuotaExceeded(RuntimeError):
    """Gemini's per-minute embedding quota is used up on every key; try again in a minute."""


class _ServerError(RuntimeError):
    pass


@lru_cache
def _http() -> httpx.Client:
    return httpx.Client(timeout=DOCUMENT_TIMEOUT, transport=http_transport())


def _normalise(v: list[float]) -> list[float]:
    # Below 3072 dimensions Gemini returns unnormalised vectors.
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _call(key: str, texts: list[str], task: str, timeout: float) -> list[list[float]]:
    s = get_settings()
    model = s.gemini_embedding_model
    body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]}, "taskType": task,
                          "outputDimensionality": s.embedding_dim} for t in texts]}
    r = _http().post(f"{API}/models/{model}:batchEmbedContents", headers={"x-goog-api-key": key}, json=body,
                     timeout=timeout)
    if r.status_code in (429, 401, 403):
        raise KeyUnavailable(r.status_code, r.text[:160])
    if r.status_code >= 500:
        raise _ServerError(f"{r.status_code} {r.text[:160]}")
    r.raise_for_status()
    return [_normalise(e["values"]) for e in r.json()["embeddings"]]


def _embed(texts: list[str], task: str, timeout: float) -> list[list[float]]:
    try:
        return with_failover(lambda key: _call(key, texts, task, timeout))
    except KeyUnavailable as e:
        if e.code == 429:
            raise EmbeddingQuotaExceeded(str(e)[:200]) from e
        raise LLMUnavailable(f"No Gemini key was accepted ({e.code}).") from e


@retry(retry=retry_if_exception(lambda e: isinstance(e, (_ServerError, httpx.TransportError))),
       wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(5), reraise=True)
def _embed_documents_batch(texts: list[str]) -> list[list[float]]:
    # 429 is not retried here: the caller pauses and resumes the job a minute later.
    return _embed(texts, "RETRIEVAL_DOCUMENT", DOCUMENT_TIMEOUT)


def embed_documents(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        out.extend(_embed_documents_batch([t[:MAX_CHARS] or " " for t in texts[i: i + BATCH]]))
    return out


def embed_query(text: str) -> list[float] | None:
    """None when embeddings aren't available, so search falls back to keywords. Someone is
    waiting: one try per key, a few seconds at most."""
    try:
        return _embed([text[:MAX_CHARS]], "RETRIEVAL_QUERY", QUERY_TIMEOUT)[0]
    except (LLMUnavailable, EmbeddingQuotaExceeded):
        return None
    except Exception as e:  # noqa: BLE001 - timeouts, network: search goes on without meaning
        log.warning("query embedding failed: %s", e)
        return None
