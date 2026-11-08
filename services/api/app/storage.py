"""Uploaded source files on disk: <STORAGE_DIR>/<project>/<source>/<file>."""

import re
import shutil
import uuid
from pathlib import Path

from app.config import get_settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def source_dir(project_id: uuid.UUID, source_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / str(project_id) / str(source_id)


def safe_name(name: str) -> str:
    """Keep the user's file name readable but strip anything path-like."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base).strip(" .")
    return base[:150] or "upload"


def save_upload(project_id: uuid.UUID, source_id: uuid.UUID, name: str, data: bytes) -> Path:
    folder = source_dir(project_id, source_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name(name)
    path.write_bytes(data)
    return path


def list_files(project_id: uuid.UUID, source_id: uuid.UUID) -> list[Path]:
    folder = source_dir(project_id, source_id)
    return sorted(p for p in folder.iterdir() if p.is_file()) if folder.exists() else []


def delete_source_files(project_id: uuid.UUID, source_id: uuid.UUID) -> None:
    shutil.rmtree(source_dir(project_id, source_id), ignore_errors=True)
