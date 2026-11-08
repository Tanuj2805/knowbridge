import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import embeddings, logs
from app.auth import CurrentUser
from app.config import get_settings
from app.db.session import engine
from app.routers import demo, evidence, projects, sources
from app.schemas import UserOut

logs.configure()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Load the local search model in the background so the first search isn't slow.
    e = embeddings.embedder()
    if hasattr(e, "warm_up"):
        threading.Thread(target=e.warm_up, name="warm-embeddings", daemon=True).start()
    yield


app = FastAPI(title="KnowBridge API", version="0.1.0", lifespan=lifespan)
app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(evidence.router)
app.include_router(demo.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    s = get_settings()
    return {
        "ok": True,
        "authz": s.authz_backend,
        "demo_mode": s.demo_mode,
        "llm_configured": bool(s.gemini_api_key),
        "search_model": embeddings.current_model_id(),
    }


@app.get("/me", response_model=UserOut, tags=["meta"])
def me(user: CurrentUser):
    return user
