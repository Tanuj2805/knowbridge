"""The only place that talks to Gemini. Everything else goes through here, so
budgets, retries and tracing live in one spot."""

from functools import lru_cache

from google import genai

from app.config import get_settings


class LLMUnavailable(RuntimeError):
    """No API key configured, or the service is down after retries."""


@lru_cache
def client() -> genai.Client:
    key = get_settings().gemini_api_key
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=key)


def configured() -> bool:
    return bool(get_settings().gemini_api_key)
