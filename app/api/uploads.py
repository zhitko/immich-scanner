from collections.abc import Iterator

from fastapi import APIRouter, Depends
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.jobs.queue import enqueue_job
from app.models import Job, Region, Scan
from app.retouch.options import retouch_is_current
from app.schemas import BulkUploadRequest, BulkUploadSummary

router = APIRouter(prefix="/uploads", tags=["uploads"])


def bulk_candidates(
    session: Session, include_uploaded: bool, summary: BulkUploadSummary
) -> Iterator[Region]:
    active_upload = exists().where(
        Job.scan_id == Scan.id,
        Job.type == "upload",
        Job.status.in_(("queued", "running")),
    )
    active_retouch = exists().where(
        Job.region_id == Region.id,
        Job.type == "retouch",
        Job.status.in_(("queued", "running")),
    )
    query = (
        select(Region, Scan.files_deleted, Scan.original_path, active_upload, active_retouch)
        .join(Scan, Region.scan_id == Scan.id)
        .order_by(Scan.created_at, Scan.id, Region.position)
    )
    for region, deleted, original, uploading, retouching in session.execute(query).yield_per(200):
        summary.total += 1
        if deleted or not original:
            summary.unavailable += 1
        elif (
            uploading
            or retouching
            or region.upload_status == "uploading"
            or region.retouch_status in {"queued", "running"}
        ):
            summary.busy += 1
        elif not include_uploaded and region.upload_status == "uploaded":
            summary.uploaded += 1
        elif region.upload_source == "retouch" and not retouch_is_current(region):
            summary.retouch_not_ready += 1
        else:
            summary.eligible += 1
            yield region


@router.get("/bulk", response_model=BulkUploadSummary)
def preview_bulk_upload(
    include_uploaded: bool = False,
    session: Session = Depends(get_session),
) -> BulkUploadSummary:
    summary = BulkUploadSummary()
    for _region in bulk_candidates(session, include_uploaded, summary):
        pass
    return summary


@router.post("/bulk", response_model=BulkUploadSummary, status_code=202)
def run_bulk_upload(
    body: BulkUploadRequest,
    session: Session = Depends(get_session),
) -> BulkUploadSummary:
    summary = BulkUploadSummary()
    # Collect before queueing so a new scan-wide job cannot hide other photos.
    scans: dict[str, list[str]] = {}
    for region in bulk_candidates(session, body.include_uploaded, summary):
        scans.setdefault(region.scan_id, []).append(region.id)
    for scan_id, region_ids in scans.items():
        enqueue_job(
            session,
            job_type="upload",
            scan_id=scan_id,
            payload={"scan_id": scan_id, "region_ids": region_ids},
        )
        summary.queued += len(region_ids)
    return summary
