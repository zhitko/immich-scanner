import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import Job


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    scan_id: str | None = None,
    region_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> Job:
    active = session.scalar(
        select(Job).where(
            Job.type == job_type,
            Job.scan_id == scan_id,
            Job.region_id == region_id,
            Job.status.in_(("queued", "running")),
        )
    )
    if active is not None and job_type == "detect":
        return active
    job = Job(
        id=str(uuid4()),
        type=job_type,
        status="queued",
        scan_id=scan_id,
        region_id=region_id,
        payload=json.dumps(payload or {}),
        error=None,
        attempts=0,
        created_at=utcnow(),
        started_at=None,
        finished_at=None,
    )
    session.add(job)
    session.flush()
    return job
