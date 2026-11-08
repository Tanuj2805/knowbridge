"""Test setup. Database tests run against a separate `<db>_test` database with
the local Gatekeeper backend and no Gemini key, so they're fast and offline."""

import os
import tempfile
from pathlib import Path

import pytest

from app.config import Settings, get_settings

_base = Settings()
_url = _base.database_url.rsplit("/", 1)
TEST_DB = f"{_url[1]}_test"
os.environ["DATABASE_URL"] = f"{_url[0]}/{TEST_DB}"
os.environ["AUTHZ_BACKEND"] = "local"
os.environ["GEMINI_API_KEY"] = ""
os.environ["EMBEDDING_PROVIDER"] = "off"  # tests never download a model; see test_embeddings.py
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="kb-test-storage-")
get_settings.cache_clear()

DATA = Path(__file__).resolve().parents[3] / "data" / "nimbus"


def _ensure_database() -> bool:
    import psycopg

    admin = _base.psycopg_url
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute("select 1 from pg_database where datname = %s", (TEST_DB,)).fetchone()
            if not exists:
                conn.execute(f'create database "{TEST_DB}"')
    except psycopg.OperationalError:
        return False
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")
    return True


@pytest.fixture(scope="session")
def database() -> None:
    if not _ensure_database():
        pytest.skip("Postgres isn't reachable (start it with: docker compose up -d postgres)")


@pytest.fixture
def db(database):
    from app.db.session import SessionLocal

    session = SessionLocal()
    yield session
    session.close()
