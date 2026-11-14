from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The API reads the repo-root .env when run outside Docker (inside Docker the
# file tree is shallower and settings come from the environment instead).
_parents = Path(__file__).resolve().parents
_ROOT_ENV = _parents[3] / ".env" if len(_parents) > 3 else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    database_url: str = "postgresql+psycopg://knowbridge:knowbridge@localhost:5432/knowbridge"

    gemini_api_key: str = ""
    # More keys (comma-separated), used in turn when the one in use is out of quota or refused.
    gemini_api_key_backup: str = ""
    # Reach outside APIs over IPv4 only. Where IPv6 is listed but doesn't route, Python otherwise
    # spends ~20 s per IPv6 address before trying IPv4. Turn off on an IPv6-only network.
    http_ipv4_only: bool = True
    gemini_model_reasoning: str = "gemini-3.6-flash"
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    # Which API the agents use: "gemini", or "openai" for any OpenAI-compatible endpoint
    # (ASI:One, Groq, OpenRouter, a local Ollama or vLLM server). Search embeddings are separate.
    llm_provider: Literal["gemini", "openai"] = "gemini"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_reasoning: str = ""
    llm_model_fast: str = ""
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
    # Requests per minute we allow ourselves per model (free tier is low; raise on a paid key).
    llm_rpm_reasoning: int = 8
    llm_rpm_fast: int = 12
    # Model calls an agent may have in flight at once. 1 suits Gemini's free tier; a provider
    # with a roomier limit (ASI:One: 200 calls per 15 minutes) runs much faster at 4.
    llm_parallel: int = 1
    # Strictest label whose text agents may send to Gemini. Confidential stays out by default,
    # consistent with search; such items reach the ledger only through people (Gap Interview).
    llm_external_max_label: Literal["team", "restricted", "confidential"] = "restricted"
    # "Ask the project" (app/rag.py) can use its own model, e.g. a small hosted Qwen: any
    # OpenAI-compatible endpoint. Empty = the agents' model above. Answering from retrieved text
    # suits small models; the agents' extraction work doesn't.
    llm_ask_base_url: str = ""
    llm_ask_api_key: str = ""
    llm_ask_model: str = ""
    llm_ask_rpm: int = 30
    # Set false only for a model on this machine or network (Ollama, vLLM): then the external
    # label cap above doesn't apply to what Ask sends it.
    llm_ask_external: bool = True
    # How much retrieved text Ask hands the model, in tokens (about 4 characters each). Small
    # models read best with a short, focused context.
    rag_context_tokens: int = 6000
    # Guardrails: questions one person may ask per minute and per day, and context exports
    # (the retrieve API, the context file) per minute. 0 turns a limit off.
    rag_ask_per_minute: int = 20
    rag_ask_per_day: int = 400
    rag_export_per_minute: int = 30
    # Dates in claims and in the evidence agents read ("since 20 Oct") use this zone.
    timezone: str = "Asia/Kolkata"

    authz_backend: Literal["openfga", "local"] = "openfga"
    openfga_api_url: str = "http://localhost:8081"

    api_jwt_secret: str = "dev-only-change-me-dev-only-change-me-dev-only"
    demo_mode: bool = True
    # "Sign in as any email" for local testing. The web app also refuses it in production builds.
    dev_login: bool = False
    # The website's address, for links the editor extension and MCP server show ("open in KnowBridge").
    web_url: str = "http://localhost:3000"
    # How long a new personal access token lasts.
    token_days: int = 90
    # Live sync: the worker re-reads live sources (GitHub, Jira) this often, looking only at what
    # changed; 0 turns the schedule off (manual "Check for changes" still works). Once every
    # `full_sync_hours` the read is a full one, which also notices items deleted at the source.
    live_sync_hours: float = 6.0
    full_sync_hours: float = 24.0

    # Email-and-password accounts (alongside the demo personas), confirmed with a code sent by email.
    password_auth: bool = True
    # The name in account emails and their sender line.
    app_name: str = "KnowBridge"
    # Outgoing email for "confirm your address" and "reset your password". Any SMTP service works
    # (Gmail with an app password, Resend, Brevo, SendGrid...). Unset: the link is written to the API
    # log instead, which is fine on your own computer but means nobody receives it on a live site.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_ssl: bool = False  # True for port 465 (SSL from the start); False uses STARTTLS
    mail_from: str = ""  # e.g. "KnowBridge <no-reply@yourdomain.com>"; defaults to smtp_user
    # Brevo's HTTPS email API, for hosts that block SMTP ports (Railway's Hobby plan does). When set,
    # it is used instead of SMTP. MAIL_FROM must be a sender verified in Brevo.
    brevo_api_key: str = ""

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

    @field_validator("database_url")
    @classmethod
    def _use_psycopg(cls, url: str) -> str:
        """Hosted databases (Railway, Neon, Render…) hand out postgres:// or postgresql:// URLs;
        the app talks to Postgres through psycopg 3, so those work as they are."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL (for LangGraph's checkpointer, which uses psycopg directly)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
