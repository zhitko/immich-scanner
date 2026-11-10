from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Job
from app.schemas import JobOut, JobStatistics

router = APIRouter(prefix="/jobs", tags=["jobs"])

_STATUSES = {"queued", "running", "finished", "failed"}


@router.get("", response_model=list[JobOut])
def list_jobs(status: str | None = None, session: Session = Depends(get_session)) -> list[JobOut]:
    query = select(Job).order_by(Job.created_at.desc()).limit(200)
    if status is not None:
        if status not in _STATUSES:
            raise HTTPException(status_code=422, detail="unknown job status")
        query = query.where(Job.status == status)
    return [_job_out(job) for job in session.scalars(query)]


@router.get("/statistics", response_model=JobStatistics)
def job_statistics(session: Session = Depends(get_session)) -> JobStatistics:
    query = select(Job.status, func.count(Job.id)).group_by(Job.status)
    counts = dict(session.execute(query).all())
    return JobStatistics(**{status: counts.get(status, 0) for status in _STATUSES})


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_out(job)


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        scan_id=job.scan_id,
        region_id=job.region_id,
        error=job.error,
        attempts=job.attempts,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
