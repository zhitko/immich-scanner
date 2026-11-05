import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.jobs.handlers import needs_upload
from app.models import Job, Region, Scan
from app.retouch.options import (
    flags_restore_faces,
    geometry_signature,
    retouch_is_current,
    stored_geometry,
)
from app.retouch.progress import retouch_progress
from app.schemas import RegionOut, ScanDetail, ScanSummary


def _retouch_version(region: Region) -> str:
    """Each retouch run writes a new path, so this changes only when the pixels do."""

    return hashlib.sha1((region.retouch_path or "").encode()).hexdigest()[:12]


def region_out(region: Region) -> RegionOut:
    stored = stored_geometry(region.uploaded_crop_signature)
    changed = bool(stored) and stored != geometry_signature(region)
    ready = retouch_is_current(region)
    status = region.retouch_status or "none"
    return RegionOut(
        id=region.id,
        position=region.position,
        center_x=region.center_x,
        center_y=region.center_y,
        width=region.width,
        height=region.height,
        angle_deg=region.angle_deg,
        quarter_turns=region.quarter_turns,
        taken_at=region.taken_at,
        description=region.description,
        album_id=region.album_id,
        latitude=region.latitude,
        longitude=region.longitude,
        is_favorite=region.is_favorite,
        rating=region.rating,
        visibility=region.visibility,
        upload_status=region.upload_status,
        immich_asset_id=region.immich_asset_id,
        immich_status=region.immich_status,
        album_linked=region.album_linked,
        metadata_synced=region.metadata_synced,
        upload_error=region.upload_error,
        uploaded_at=region.uploaded_at,
        crop_changed=changed,
        needs_upload=needs_upload(region),
        retouch_upscale=bool(region.retouch_upscale),
        retouch_faces=bool(region.retouch_faces),
        retouch_colorize=bool(region.retouch_colorize),
        retouch_scratches=bool(region.retouch_scratches),
        upload_source=region.upload_source or "crop",
        retouch_status=status,
        retouch_progress=retouch_progress(region.id) if status == "running" else None,
        retouch_error=region.retouch_error,
        retouch_signature=region.retouch_signature,
        retouch_ready=ready,
        retouch_version=_retouch_version(region) if ready else None,
        retouch_reconstructs_faces=ready and flags_restore_faces(region.retouch_signature),
        updated_at=region.updated_at,
    )


def scan_summary(session: Session, scan: Scan) -> ScanSummary:
    counts = session.execute(
        select(
            func.count(Region.id),
            func.count(Region.id).filter(Region.upload_status == "uploaded"),
        ).where(Region.scan_id == scan.id)
    ).one()
    detecting = session.scalar(
        select(func.count(Job.id)).where(
            Job.scan_id == scan.id,
            Job.type == "detect",
            Job.status.in_(("queued", "running")),
        )
    )
    return ScanSummary(
        id=scan.id,
        created_at=scan.created_at,
        width=scan.width,
        height=scan.height,
        dpi=scan.dpi,
        device_name=device_name(scan),
        upload_state=scan.upload_state,
        files_deleted=scan.files_deleted,
        detection_error=scan.detection_error,
        detecting=bool(detecting),
        region_count=int(counts[0]),
        uploaded_count=int(counts[1]),
        original_filename=scan.original_filename,
    )


def scan_detail(session: Session, scan: Scan) -> ScanDetail:
    summary = scan_summary(session, scan)
    regions = session.scalars(
        select(Region).where(Region.scan_id == scan.id).order_by(Region.position)
    ).all()
    return ScanDetail(**summary.model_dump(), regions=[region_out(region) for region in regions])


def device_name(scan: Scan) -> str | None:
    return scan.device_name or None
