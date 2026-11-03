from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_services, get_session, require_scanner_token
from app.clock import utcnow
from app.imaging.crop import resize_max_edge
from app.imaging.io import load_rgb, save_rgb
from app.jobs.queue import enqueue_job
from app.models import Scan
from app.runtime import Services
from app.schemas import IngestResult

router = APIRouter(prefix="/ingest", tags=["ingest"])

_MAX_BYTES = 500 * 1024 * 1024
_KNOWN_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


@router.post("/scans", response_model=IngestResult, status_code=201)
def ingest_scan(
    file: UploadFile = File(...),
    dpi: int = Form(default=300),
    device_name: str = Form(default=""),
    filename: str = Form(default=""),
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
    _auth: None = Depends(require_scanner_token),
) -> IngestResult:
    if not 50 <= dpi <= 4800:
        raise HTTPException(status_code=422, detail="dpi is out of range")
    scan_id = str(uuid4())
    directory = services.storage.scan_directory(scan_id)
    safe_name = Path(filename or file.filename or "scan.tif").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _KNOWN_SUFFIXES:
        suffix = ".tif"
    destination = directory / f"original{suffix}"
    written = _copy_upload(file, destination)
    if written == 0 or written > _MAX_BYTES:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="scan file is empty or larger than 500 MB")
    try:
        image, embedded_dpi = load_rgb(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not read the scan: {exc}") from exc
    height, width = image.shape[:2]
    preview_path = directory / "preview.jpg"
    save_rgb(resize_max_edge(image, 1800), preview_path, "jpeg", jpeg_quality=82)
    now = utcnow()
    scan = Scan(
        id=scan_id,
        created_at=now,
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
    return IngestResult(scan_id=scan_id, job_id=job.id)


def _copy_upload(upload: UploadFile, destination: Path) -> int:
    written = 0
    with destination.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_BYTES:
                break
            handle.write(chunk)
    return written
