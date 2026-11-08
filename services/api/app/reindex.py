"""Build smart-search vectors: python -m app.reindex [--project <id>]

Embeds every item without a vector from the current model (EMBEDDING_PROVIDER).
Safe to re-run: items that are already done are skipped.
"""

import argparse
import sys
import time
import uuid

from sqlalchemy import select

from app import embeddings, ingest, logs
from app.db.models import Project
from app.db.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.reindex")
    parser.add_argument("--project", type=uuid.UUID, help="only this project")
    args = parser.parse_args()
    logs.configure()
    model = embeddings.current_model_id()
    if model is None:
        print("Smart search is off (EMBEDDING_PROVIDER=off, or gemini without a key).")
        return 1
    print(f"Model: {model}")
    with SessionLocal() as db:
        projects = [db.get(Project, args.project)] if args.project else db.scalars(select(Project)).all()
        quota = embeddings.embedder().items_per_minute
        if quota:
            print(f"Provider quota: {quota} items/minute, so this pauses between portions.")
        for p in projects:
            t0, total = time.time(), 0
            while True:
                total += ingest.embed_missing(db, project_id=p.id, max_items=quota)
                left = ingest.count_missing(db, p.id)
                print(f"  {p.name:45} {total:5} embedded, {left:5} left  ({time.time() - t0:.0f}s)", flush=True)
                if not left:
                    break
                time.sleep(61)
    return 0


if __name__ == "__main__":
    sys.exit(main())
