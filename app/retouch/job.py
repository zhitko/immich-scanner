import logging
import os
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.imaging.crop import upright_crop
from app.imaging.io import load_rgb, save_rgb
from app.imaging.preview import drop_previews, retouch_preview_path, write_retouch_preview
from app.models import Job, Region, Scan
from app.retouch.options import (
    expected_retouch_signature,
    options_from_region,
)
from app.retouch.progress import clear_retouch_progress, set_retouch_progress, set_retouch_stage
from app.runtime import Services

logger = logging.getLogger(__name__)


def handle_retouch(session: Session, job: Job, services: Services) -> None:
    region_id = job.region_id or ""
    region = session.get(Region, region_id) if region_id else None
    if region is None:
        return
    scan = session.get(Scan, region.scan_id)
    if scan is None or scan.files_deleted or not scan.original_path:
        raise RuntimeError("scan file is not available")
    options = options_from_region(region)
    if not options.any_selected():
        raise RuntimeError("Choose at least one retouch stage.")
    produced = expected_retouch_signature(region)
    center_x = region.center_x
    center_y = region.center_y
    width = region.width
    height = region.height
    angle_deg = region.angle_deg
    quarter_turns = region.quarter_turns
    original_path = scan.original_path
    previous_path = region.retouch_path
    scan_id = scan.id
    clear_retouch_progress(region_id)
    set_retouch_progress(region_id, 0)
    region.retouch_status = "running"
    region.retouch_error = None
    region.updated_at = utcnow()
    session.commit()

    crop_relative = f"scans/{scan_id}/crops/{region_id}.png"
    # A new name per run: the old file stays valid until this run is committed.
    retouch_relative = f"scans/{scan_id}/retouch/{region_id}-{job.id[:8]}.png"
    retouch_file = services.storage.absolute(retouch_relative)
    preview_file = retouch_preview_path(services, scan_id, region_id, retouch_relative)
    try:
        image, _dpi = load_rgb(services.storage.absolute(original_path))
        upright = upright_crop(
            image,
            center_x,
            center_y,
            width,
            height,
            angle_deg,
            quarter_turns,
        )
        del image
        _save_png(upright, services.storage.absolute(crop_relative))
        derivative = services.retoucher.apply(
            upright,
            options,
            on_progress=lambda percent: set_retouch_progress(region_id, percent),
            on_stage=lambda stage: set_retouch_stage(region_id, stage),
        )
        del upright
        # The large PNG and its preview are still ahead. Hold the bar at 99 until they land.
        set_retouch_progress(region_id, 99)
        _save_png(derivative, retouch_file)
        write_retouch_preview(derivative, preview_file)
        del derivative
    except Exception as exc:
        clear_retouch_progress(region_id)
        retouch_file.unlink(missing_ok=True)
        preview_file.unlink(missing_ok=True)
        session.rollback()
        failed = session.get(Region, region_id)
        if failed is not None:
            waiting = _another_retouch_is_queued(session, region_id, job.id)
            failed.retouch_status = "queued" if waiting else "failed"
            failed.retouch_error = None if waiting else str(exc)[:2000]
            if not waiting and failed.upload_source == "retouch":
                failed.upload_source = "crop"
            failed.updated_at = utcnow()
            session.commit()
        raise

    try:
        current = session.get(Region, region_id)
        if current is None:
            retouch_file.unlink(missing_ok=True)
            drop_previews(services, scan_id, region_id)
            services.storage.absolute(crop_relative).unlink(missing_ok=True)
            return
        current.crop_path = crop_relative
        current.retouch_path = retouch_relative
        current.retouch_signature = produced
        current.retouch_error = None
        current.updated_at = utcnow()
        if _another_retouch_is_queued(session, region_id, job.id):
            current.retouch_status = "queued"
        elif expected_retouch_signature(current) == produced:
            current.retouch_status = "ready"
        else:
            current.retouch_status = "stale"
            if current.upload_source == "retouch":
                current.upload_source = "crop"
        session.commit()
    finally:
        clear_retouch_progress(region_id)
    if previous_path and previous_path != retouch_relative:
        services.storage.absolute(previous_path).unlink(missing_ok=True)
    drop_previews(services, scan_id, region_id, folders=("retouch-previews",), keep=preview_file)
    logger.info("retouched region %s on scan %s", region_id, scan_id)


def abandon_retouch(session: Session, job: Job, reason: str) -> None:
    """The worker gave up on this job. Leave the photo failed instead of running."""

    region = session.get(Region, job.region_id) if job.region_id else None
    if region is None or region.retouch_status not in {"queued", "running"}:
        return
    clear_retouch_progress(region.id)
    if _another_retouch_is_queued(session, region.id, job.id):
        region.retouch_status = "queued"
        return
    region.retouch_status = "failed"
    region.retouch_error = reason
    if region.upload_source == "retouch":
        region.upload_source = "crop"
    region.updated_at = utcnow()


def _another_retouch_is_queued(session: Session, region_id: str, job_id: str) -> bool:
    waiting = session.scalar(
        select(Job.id).where(
            Job.type == "retouch",
            Job.region_id == region_id,
            Job.status == "queued",
            Job.id != job_id,
        )
    )
    return waiting is not None


def _save_png(image, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    save_rgb(image, partial, "png")
    os.replace(partial, path)
