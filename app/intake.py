import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clock import utcnow
from app.imaging.crop import resize_max_edge
from app.imaging.io import load_rgb, save_rgb
from app.jobs.queue import enqueue_job
from app.models import Scan
from app.runtime import Services

_MAX_BYTES = 500 * 1024 * 1024
_KNOWN_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


class IntakeError(Exception):
    """A captured bed image could not be stored."""


@dataclass(frozen=True)
class RegisteredScan:
    scan_id: str
    job_id: str


def register_scan(
    session: Session,
    services: Services,
    source: Path,
    *,
    dpi: int,
    device_name: str,
    filename: str,
) -> RegisteredScan:
    """Move a finished bed image into the archive and queue detection."""

    if not 50 <= dpi <= 4800:
        raise IntakeError("dpi is out of range")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise IntakeError("scan file is missing") from exc
    if size == 0 or size > _MAX_BYTES:
        source.unlink(missing_ok=True)
        raise IntakeError("scan file is empty or larger than 500 MB")

    scan_id = str(uuid4())
    directory = services.storage.scan_directory(scan_id)
    safe_name = Path(filename or source.name).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _KNOWN_SUFFIXES:
        suffix = ".tif"
    destination = directory / f"original{suffix}"
    shutil.move(source, destination)
    try:
        image, embedded_dpi = load_rgb(destination)
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise IntakeError(f"Could not read the scan: {exc}") from exc
    height, width = image.shape[:2]
    preview_path = directory / "preview.jpg"
    save_rgb(resize_max_edge(image, 1800), preview_path, "jpeg", jpeg_quality=82)
    scan = Scan(
        id=scan_id,
        created_at=utcnow(),
        original_filename=safe_name,
        original_path=services.storage.relative(destination),
        preview_path=services.storage.relative(preview_path),
        width=width,
        height=height,
        dpi=embedded_dpi or dpi,
        device_name=device_name.strip() or None,
        upload_state="pending",
        files_deleted=False,
        detection_error=None,
    )
    session.add(scan)
    job = enqueue_job(session, job_type="detect", scan_id=scan_id, payload={"scan_id": scan_id})
    return RegisteredScan(scan_id=scan_id, job_id=job.id)
