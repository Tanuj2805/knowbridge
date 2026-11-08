from fastapi import APIRouter, HTTPException

from app import demo
from app.auth import DB, CurrentUser
from app.config import get_settings

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/nimbus", status_code=201)
def load_nimbus(user: CurrentUser, db: DB) -> dict:
    """Creates a fresh copy of Project Nimbus. Sources are ingested by the worker."""
    if not get_settings().demo_mode:
        raise HTTPException(404, "Not found.")
    try:
        project = demo.create_nimbus(db, created_by=user.id)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    return {"id": str(project.id), "name": project.name}
