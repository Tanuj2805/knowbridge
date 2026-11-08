"""Gemini embeddings (multilingual, so Hinglish chat lands near English text)."""

import logging
import math

from google.genai import errors, types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.llm import LLMUnavailable, client

log = logging.getLogger(__name__)

BATCH = 50
MAX_CHARS = 7000  # gemini-embedding-001 reads ~2k tokens; keep well inside


class EmbeddingQuotaExceeded(RuntimeError):
    """Gemini's per-minute embedding quota is used up; try again in a minute."""


def _retryable(e: BaseException) -> bool:
    # 429 is not retried here: the caller pauses and resumes the job a minute later.
    return isinstance(e, errors.APIError) and getattr(e, "code", 0) in (500, 502, 503, 504)


def _normalise(v: list[float]) -> list[float]:
    # Below 3072 dimensions Gemini returns unnormalised vectors.
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@retry(retry=retry_if_exception(_retryable), wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(5),
       reraise=True)
def _embed_batch(texts: list[str], task: str) -> list[list[float]]:
    s = get_settings()
    try:
        res = client().models.embed_content(
            model=s.gemini_embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task, output_dimensionality=s.embedding_dim),
        )
    except errors.APIError as e:
        if getattr(e, "code", 0) == 429:
            raise EmbeddingQuotaExceeded(str(e)[:200]) from e
        raise
    return [_normalise(list(e.values)) for e in res.embeddings]


def embed_documents(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        out.extend(_embed_batch([t[:MAX_CHARS] or " " for t in texts[i : i + BATCH]], "RETRIEVAL_DOCUMENT"))
    return out


def embed_query(text: str) -> list[float] | None:
    """None when embeddings aren't available, so search falls back to keywords."""
    try:
        return _embed_batch([text[:MAX_CHARS]], "RETRIEVAL_QUERY")[0]
    except (LLMUnavailable, EmbeddingQuotaExceeded):
        return None
    except errors.APIError as e:
        log.warning("query embedding failed: %s", e)
        return None
