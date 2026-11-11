import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_session
from app.api.jobs import _job_out
from app.api.scans import _apply_patch
from app.jobs.handlers import refresh_upload_state
from app.jobs.queue import enqueue_job
from app.matching import available_fields, has_field, index_signature
from app.models import Job, PhotoMatch, Region, Scan
from app.schemas import (
    MatchCopyRequest,
    MatchingRequest,
    PhotoMatchesOut,
    PhotoMatchOut,
    PhotoOut,
    RegionPatch,
)
from app.serialize import region_out

router = APIRouter(prefix="/matching", tags=["matching"])


def _active_job(session: Session) -> Job | None:
    return session.scalar(
        select(Job).where(Job.type == "match", Job.status.in_(("queued", "running")))
    )


@router.post("/run", status_code=202)
def run_matching(body: MatchingRequest, session: Session = Depends(get_session)) -> dict[str, str]:
    job = _active_job(session)
    if job is None:
        try:
            job = enqueue_job(session, job_type="match", payload=body.model_dump())
            session.commit()
        except IntegrityError:
            session.rollback()
            job = _active_job(session)
            if job is None:
                raise
    return {"job_id": job.id}


@router.get("/status")
def matching_status(session: Session = Depends(get_session)) -> dict:
    job = _active_job(session) or session.scalar(
        select(Job).where(Job.type == "match").order_by(Job.created_at.desc(), Job.id).limit(1)
    )
    return {
        "job": _job_out(job) if job else None,
        "progress": json.loads(job.payload) if job else None,
    }


def _photo(region: Region, scan: Scan) -> PhotoOut:
    return PhotoOut(
        **region_out(region).model_dump(),
        scan_id=scan.id,
        created_at=scan.created_at,
        files_deleted=scan.files_deleted,
        dpi=scan.dpi,
    )


def _current(
    match: PhotoMatch, source: Region, target: Region, source_scan: Scan, target_scan: Scan
) -> bool:
    return (
        not match.dismissed
        and not source_scan.files_deleted
        and not target_scan.files_deleted
        and bool(source_scan.original_path)
        and bool(target_scan.original_path)
        and match.source_signature == index_signature(source_scan, source)
        and match.target_signature == index_signature(target_scan, target)
    )


@router.get("/pairs", response_model=PhotoMatchesOut)
def list_pairs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> PhotoMatchesOut:
    source, target = aliased(Region), aliased(Region)
    source_scan, target_scan = aliased(Scan), aliased(Scan)
    rows = session.execute(
        select(PhotoMatch, source, target, source_scan, target_scan)
        .join(source, source.id == PhotoMatch.source_id)
        .join(target, target.id == PhotoMatch.target_id)
        .join(source_scan, source_scan.id == source.scan_id)
        .join(target_scan, target_scan.id == target.scan_id)
        .where(PhotoMatch.dismissed.is_(False))
        .order_by(PhotoMatch.score.desc(), PhotoMatch.target_id, PhotoMatch.source_id)
    )
    items = []
    total = 0
    for match, src, dst, src_scan, dst_scan in rows:
        fields = available_fields(src, dst)
        if not fields or not _current(match, src, dst, src_scan, dst_scan):
            continue
        if offset <= total < offset + limit:
            items.append(
                PhotoMatchOut(
                    source=_photo(src, src_scan),
                    target=_photo(dst, dst_scan),
                    score=match.score,
                    fields=fields,
                )
            )
        total += 1
    return PhotoMatchesOut(items=items, total=total)


@router.post("/pairs/{source_id}/{target_id}/copy", response_model=PhotoOut)
def copy_field(
    source_id: str, target_id: str, body: MatchCopyRequest, session: Session = Depends(get_session)
) -> PhotoOut:
    # Acquire SQLite's writer lock before reading either revision. Other edits cannot
    # slip in between the revision checks and this write. Replacement must be explicit.
    session.execute(
        update(Region).where(Region.id == target_id).values(updated_at=Region.updated_at)
    )
    match = session.get(PhotoMatch, (source_id, target_id))
    source, target = session.get(Region, source_id), session.get(Region, target_id)
    if match is None or source is None or target is None:
        raise HTTPException(404, "Photo match not found. Refresh the suggestions.")
    src_scan, dst_scan = session.get(Scan, source.scan_id), session.get(Scan, target.scan_id)
    if (
        source_id == target_id
        or not _current(match, source, target, src_scan, dst_scan)
        or source.updated_at != body.source_updated_at
        or target.updated_at != body.target_updated_at
        or not has_field(source, body.field)
        or (not body.replace and body.field not in available_fields(source, target))
    ):
        raise HTTPException(409, "This suggestion changed. Refresh before copying metadata.")
    values = (
        {"latitude": source.latitude, "longitude": source.longitude}
        if body.field == "location"
        else {body.field: getattr(source, body.field)}
    )
    _apply_patch(dst_scan, target, RegionPatch(**values))
    refresh_upload_state(session, dst_scan)
    session.commit()
    return _photo(target, dst_scan)


@router.post("/pairs/{source_id}/{target_id}/dismiss", status_code=204)
def dismiss_pair(source_id: str, target_id: str, session: Session = Depends(get_session)) -> None:
    result = session.execute(
        update(PhotoMatch)
        .where(PhotoMatch.source_id == source_id, PhotoMatch.target_id == target_id)
        .values(dismissed=True)
    )
    if result.rowcount != 1:
        raise HTTPException(404, "Photo match not found.")
    session.commit()
