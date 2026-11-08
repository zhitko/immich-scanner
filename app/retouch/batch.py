from collections.abc import Iterator
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Job, Region, Scan
from app.schemas import BulkRetouchSummary


def bulk_candidates(
    session: Session,
    state: Literal["open", "uploaded", "all"],
    include_retouched: bool,
    summary: BulkRetouchSummary,
) -> Iterator[Region]:
    """Count mutually exclusive skip reasons and yield only eligible photos."""

    active = exists().where(
        Job.region_id == Region.id,
        Job.type == "retouch",
        Job.status.in_(("queued", "running")),
    )
    query = (
        select(Region, Scan.files_deleted, Scan.original_path, active)
        .join(Scan, Region.scan_id == Scan.id)
        .order_by(Scan.created_at, Scan.id, Region.position)
    )
    if state == "open":
        query = query.where(Region.upload_status != "uploaded")
    elif state == "uploaded":
        query = query.where(Region.upload_status == "uploaded")
    for region, files_deleted, original_path, has_job in session.execute(query).yield_per(200):
        summary.total += 1
        if files_deleted or not original_path:
            summary.unavailable += 1
        elif (
            has_job
            or region.retouch_status in {"queued", "running"}
            or (region.upload_status == "uploading")
        ):
            summary.busy += 1
        elif not include_retouched and (region.retouch_path or region.retouch_signature):
            # Stale and failed reruns still have a previous result to preserve.
            summary.retouched += 1
        else:
            summary.eligible += 1
            yield region
