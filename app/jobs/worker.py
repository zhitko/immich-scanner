import logging
import threading

from sqlalchemy import select, update

from app.clock import utcnow
from app.jobs.handlers import handle_detect, handle_upload
from app.models import Job
from app.retouch.job import abandon_retouch, handle_retouch
from app.runtime import Services

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

HANDLERS = {
    "detect": handle_detect,
    "upload": handle_upload,
    "retouch": handle_retouch,
}


class JobWorker:
    """Poll the jobs table. A running job left behind by a crash is queued again."""

    def __init__(self, services: Services) -> None:
        self._services = services
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def recover(self) -> int:
        """Queue running jobs again. One that already took the process down too often fails."""

        session = self._services.session_factory()
        try:
            running = list(session.scalars(select(Job).where(Job.status == "running")))
            requeued = 0
            for job in running:
                if job.attempts >= MAX_ATTEMPTS:
                    reason = (
                        f"Stopped after {job.attempts} attempts. The server restarted while "
                        "this job ran, possibly out of memory."
                    )
                    job.status = "failed"
                    job.error = reason
                    job.finished_at = utcnow()
                    if job.type == "retouch":
                        abandon_retouch(session, job, reason)
                    continue
                job.status = "queued"
                job.started_at = None
                requeued += 1
            session.commit()
            return requeued
        finally:
            session.close()

    def process_available(self) -> int:
        count = 0
        while self.process_one():
            count += 1
        return count

    def process_one(self) -> bool:
        job_id = self._claim()
        if job_id is None:
            return False
        session = self._services.session_factory()
        try:
            job = session.get(Job, job_id)
            if job is None:
                return True
            handler = HANDLERS[job.type]
            handler(session, job, self._services)
            job.status = "finished"
            job.error = None
            job.finished_at = utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.exception("job %s failed", job_id)
            self._fail(job_id, exc)
        finally:
            session.close()
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.process_one():
                self._stop.wait(0.4)

    def _claim(self) -> str | None:
        session = self._services.session_factory()
        try:
            job = session.scalar(
                select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(1)
            )
            if job is None:
                return None
            job_id = job.id
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(status="running", started_at=utcnow(), attempts=Job.attempts + 1)
            )
            session.commit()
            if result.rowcount != 1:
                return None
            return job_id
        finally:
            session.close()

    def _fail(self, job_id: str, exc: Exception) -> None:
        session = self._services.session_factory()
        try:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:4000]
            job.finished_at = utcnow()
            session.commit()
        finally:
            session.close()
