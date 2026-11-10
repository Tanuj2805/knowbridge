"""The only place that talks to Gemini. Everything else goes through here, so
budgets, retries and tracing live in one spot.

Keys: GEMINI_API_KEY, then any in GEMINI_API_KEY_BACKUP (comma-separated). A call that finds its
key out of quota or refused moves to the next one, and the key that worked stays in use."""

import logging
import threading
from collections.abc import Callable
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors, types

from app.config import get_settings

log = logging.getLogger(__name__)
SWITCH_ON = (429, 401, 403)  # out of quota, or the key itself refused: try the next key


class LLMUnavailable(RuntimeError):
    """No API key configured, or the service is down after retries."""


class KeyUnavailable(RuntimeError):
    """This key can't be used right now (out of quota, or refused); another key may work."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"{code} {message}".strip())
        self.code = code


def http_transport() -> httpx.HTTPTransport:
    """For calls to outside APIs. On networks where IPv6 is listed but doesn't route, Python tries
    each IPv6 address for ~20 s before IPv4 (curl races them); binding to IPv4 skips that."""
    if get_settings().http_ipv4_only:
        return httpx.HTTPTransport(local_address="0.0.0.0")  # noqa: S104 - picks IPv4 for outgoing calls; no server
    return httpx.HTTPTransport()


def gemini_keys() -> list[str]:
    s = get_settings()
    keys = [s.gemini_api_key, *s.gemini_api_key_backup.split(",")]
    return [k for k in dict.fromkeys(k.strip() for k in keys) if k]


_active = 0
_lock = threading.Lock()


def _switchable(e: Exception) -> bool:
    return isinstance(e, KeyUnavailable) or (isinstance(e, errors.APIError) and getattr(e, "code", 0) in SWITCH_ON)


def with_failover[T](call: Callable[[str], T]) -> T:
    """Runs `call(key)` with the key in use; when that key is out of quota or refused, with each
    other key in turn. The key that worked stays in use; the last error is raised if none did."""
    global _active
    keys = gemini_keys()
    if not keys:
        raise LLMUnavailable("GEMINI_API_KEY is not set.")
    first = _active % len(keys)
    last: Exception | None = None
    for step in range(len(keys)):
        i = (first + step) % len(keys)
        try:
            result = call(keys[i])
        except Exception as e:
            if not _switchable(e):
                raise
            last = e
            if len(keys) > 1:
                log.warning("Gemini key %d of %d unavailable (%s); trying the next", i + 1, len(keys),
                            getattr(e, "code", e))
            continue
        if i != first:
            with _lock:
                _active = i
            log.info("now using Gemini key %d of %d", i + 1, len(keys))
        return result
    assert last is not None
    raise last


@lru_cache
def sdk_client(key: str) -> genai.Client:
    """The Gemini SDK for one key (the gateway's own retries handle limits, so the SDK makes one try)."""
    return genai.Client(api_key=key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))


def client() -> genai.Client:
    """The SDK with the key in use, for callers that don't need failover."""
    keys = gemini_keys()
    if not keys:
        raise LLMUnavailable("GEMINI_API_KEY is not set.")
    return sdk_client(keys[_active % len(keys)])


def configured() -> bool:
    """Whether the agents' model is set up (Gemini key, or an OpenAI-compatible endpoint)."""
    s = get_settings()
    if s.llm_provider == "openai":
        return bool(s.llm_base_url and s.llm_api_key and s.llm_model_reasoning)
    return bool(gemini_keys())
