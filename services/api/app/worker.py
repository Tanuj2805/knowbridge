"""Background worker: `python -m app.worker`."""

import logging
import signal
import time

from app import logs, tasks  # noqa: F401  (tasks registers handlers)
from app.db.session import SessionLocal
from app.jobs import WORKER_ID, claim_next, requeue_orphaned, run

log = logging.getLogger("worker")
_stop = False


def _shutdown(*_: object) -> None:
    global _stop
    _stop = True
    log.info("stopping after the current job")


def main() -> None:
    logs.configure()
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    log.info("worker %s started", WORKER_ID)
    with SessionLocal() as db:
        if n := requeue_orphaned(db):
            log.info("requeued %s jobs left running by a previous worker on this host", n)
    idle = 0.5
    while not _stop:
        with SessionLocal() as db:
            job = claim_next(db)
            if job is None:
                time.sleep(idle)
                idle = min(idle * 1.5, 3.0)
                continue
            idle = 0.5
            log.info("running job %s (%s)", job.id, job.kind)
            run(db, job)


if __name__ == "__main__":
    main()
