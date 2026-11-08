from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The API reads the repo-root .env when run outside Docker (inside Docker the
# file tree is shallower and settings come from the environment instead).
_parents = Path(__file__).resolve().parents
_ROOT_ENV = _parents[3] / ".env" if len(_parents) > 3 else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    database_url: str = "postgresql+psycopg://knowbridge:knowbridge@localhost:5432/knowbridge"

    gemini_api_key: str = ""
    gemini_model_reasoning: str = "gemini-3.6-flash"
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    # Meaning search: "gemini" (default; nothing to host), "local" runs a model on this
    # server (needs ~1.5 GB RAM and `pip install .[local-search]`), "off" is keyword-only.
    embedding_provider: Literal["local", "gemini", "off"] = "gemini"
    # Gemini's free tier allows 100 embeddings a minute; stay under it and leave room
    # for search queries. Raise on a paid plan. Ignored for the local model.
    embed_items_per_minute: int = 90
    # The strictest label whose text may be sent to an *external* embedding provider
    # (Gemini). Confidential items stay keyword-only unless this is "confidential".
    # The local provider ignores it: nothing leaves the server.
    embed_external_max_label: Literal["team", "restricted", "confidential"] = "restricted"
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    model_cache_dir: Path = Path("./.models")
    run_max_llm_calls: int = 400
    run_max_tokens: int = 2_000_000

    authz_backend: Literal["openfga", "local"] = "openfga"
    openfga_api_url: str = "http://localhost:8081"

    api_jwt_secret: str = "dev-only-change-me-dev-only-change-me-dev-only"
    demo_mode: bool = True

    # Encrypts stored connector credentials. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secrets_key: str = ""

    github_token: str = ""
    # Jira connector: only Jira Cloud sites (*.atlassian.net) unless this is on,
    # so a user-supplied URL can't make the server call internal hosts.
    jira_allow_any_host: bool = False
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"
    storage_dir: Path = Path("./storage")
    # Repo's data/ folder (demo datasets). Mounted at /srv/data in Docker.
    data_dir: Path = Path(__file__).resolve().parents[3] / "data" if len(_parents) > 3 else Path("/srv/data")

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    log_level: str = "INFO"

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL (for LangGraph's checkpointer, which uses psycopg directly)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
