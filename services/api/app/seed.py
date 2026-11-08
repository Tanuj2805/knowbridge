"""python -m app.seed nimbus [--reset] [--no-sync]

Creates Project Nimbus and ingests all its sources right here (no worker
needed). --reset deletes earlier Project Nimbus copies first.
"""

import argparse
import sys

from sqlalchemy import select

from app import demo, ingest, logs, storage
from app.db.models import Project, Source
from app.db.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed")
    parser.add_argument("dataset", choices=["nimbus"])
    parser.add_argument("--reset", action="store_true", help="delete existing Project Nimbus copies first")
    parser.add_argument("--no-sync", action="store_true", help="queue the syncs for the worker instead")
    args = parser.parse_args()
    logs.configure()

    with SessionLocal() as db:
        if args.reset:
            for p in db.scalars(select(Project).where(Project.name.like("Project Nimbus%"))).all():
                for s in db.scalars(select(Source).where(Source.project_id == p.id)):
                    storage.delete_source_files(p.id, s.id)
                db.delete(p)
            db.commit()

        project = demo.create_nimbus(db, enqueue=args.no_sync)
        print(f"Created {project.name} ({project.id})")
        if args.no_sync:
            print("Sources queued; start the worker to ingest them.")
            return 0
        for source in db.scalars(select(Source).where(Source.project_id == project.id)).all():
            report = ingest.sync_source(db, source.id)
            print(f"  {source.name:28} {report.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
