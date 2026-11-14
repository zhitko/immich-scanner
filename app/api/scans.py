from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_services, get_session
from app.clock import utcnow
from app.geometry import ensure_geometry
from app.imaging.preview import drop_previews, region_preview, retouch_preview
from app.immich.gateway import ImmichError
from app.jobs.handlers import refresh_upload_state
from app.jobs.queue import enqueue_job
from app.models import Region, Scan
from app.retouch.options import retouch_is_current, sync_retouch_status
from app.runtime import Services
from app.schemas import (
    RegionCreate,
    RegionOut,
    RegionPatch,
    RetouchQueued,
    RetouchRequest,
    ScanDetail,
    ScanSummary,
    UploadRequest,
)
from app.serialize import region_out, scan_detail, scan_summary
from app.settings_store import apply_processing_defaults, load_settings, retouch_columns

router = APIRouter(prefix="/scans", tags=["scans"])

_META_FIELDS = {
    "taken_at",
    "description",
    "is_favorite",
    "latitude",
    "longitude",
    "rating",
    "visibility",
}
_RETOUCH_FIELDS = {
    "center_x",
    "center_y",
    "width",
    "height",
    "angle_deg",
    "quarter_turns",
    "retouch_upscale",
    "retouch_denoise",
    "retouch_faces",
    "retouch_colorize",
    "retouch_scratches",
    "retouch_color_balance",
    "retouch_contrast",
    "retouch_dust",
    "retouch_deblur",
    "retouch_gentle_denoise",
    "retouch_paper_mesh",
    "retouch_paper_embossed",
    "retouch_light_corners",
    "retouch_output_scale",
}


@router.get("", response_model=list[ScanSummary])
def list_scans(
    state: str = "open",
    session: Session = Depends(get_session),
) -> list[ScanSummary]:
    query = select(Scan).order_by(Scan.created_at.desc()).limit(500)
    if state == "uploaded":
        query = query.where(Scan.upload_state == "complete")
    elif state == "open":
        query = query.where(Scan.upload_state != "complete")
    elif state != "all":
        raise HTTPException(status_code=422, detail="state must be open, uploaded, or all")
    return [scan_summary(session, scan) for scan in session.scalars(query)]


@router.get("/{scan_id}", response_model=ScanDetail)
def get_scan(
    scan_id: str,
    apply_defaults: bool = False,
    session: Session = Depends(get_session),
) -> ScanDetail:
    scan = _scan(session, scan_id)
    if apply_defaults and not scan.files_deleted:
        stored = load_settings(session)
        for region in session.scalars(select(Region).where(Region.scan_id == scan.id)):
            apply_processing_defaults(region, stored)
        session.commit()
    return scan_detail(session, scan)


@router.delete("/{scan_id}", status_code=204)
def delete_scan(
    scan_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> None:
    scan = _scan(session, scan_id)
    services.storage.remove_tree(scan.id)
    session.delete(scan)


@router.delete("/{scan_id}/files", response_model=ScanDetail)
def delete_scan_files(
    scan_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> ScanDetail:
    scan = _scan(session, scan_id)
    services.storage.remove_tree(scan.id)
    scan.original_path = None
    scan.preview_path = None
    scan.files_deleted = True
    return scan_detail(session, scan)


@router.post("/{scan_id}/detect", status_code=202)
def redetect(
    scan_id: str,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    scan = _scan(session, scan_id)
    _require_files(scan)
    job = enqueue_job(session, job_type="detect", scan_id=scan.id, payload={"scan_id": scan.id})
    return {"job_id": job.id}


@router.post("/{scan_id}/upload", status_code=202)
def upload_scan(
    scan_id: str,
    body: UploadRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    scan = _scan(session, scan_id)
    _require_files(scan)
    payload: dict[str, object] = {"scan_id": scan.id, "force_upload": True}
    if body and body.region_ids:
        payload["region_ids"] = body.region_ids
    job = enqueue_job(session, job_type="upload", scan_id=scan.id, payload=payload)
    return {"job_id": job.id}


@router.get("/{scan_id}/preview")
def scan_preview(
    scan_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> FileResponse:
    scan = _scan(session, scan_id)
    if scan.files_deleted or not scan.preview_path:
        raise HTTPException(status_code=404, detail="scan files were deleted")
    return FileResponse(services.storage.absolute(scan.preview_path), media_type="image/jpeg")


@router.get("/{scan_id}/original")
def scan_original(
    scan_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> FileResponse:
    scan = _scan(session, scan_id)
    if scan.files_deleted or not scan.original_path:
        raise HTTPException(status_code=404, detail="scan files were deleted")
    path = services.storage.absolute(scan.original_path)
    return FileResponse(
        path,
        media_type=_media_type(path.suffix.lower()),
        filename=scan.original_filename,
    )


@router.post("/{scan_id}/regions", response_model=RegionOut, status_code=201)
def create_region(
    scan_id: str,
    body: RegionCreate,
    session: Session = Depends(get_session),
) -> RegionOut:
    scan = _scan(session, scan_id)
    ensure_geometry(
        scan,
        center_x=body.center_x,
        center_y=body.center_y,
        width=body.width,
        height=body.height,
        angle_deg=body.angle_deg,
    )
    positions = session.scalars(select(Region.position).where(Region.scan_id == scan.id)).all()
    now = utcnow()
    stored = load_settings(session)
    region = Region(
        id=str(uuid4()),
        scan_id=scan.id,
        position=(max(positions) if positions else 0) + 1,
        center_x=body.center_x,
        center_y=body.center_y,
        width=body.width,
        height=body.height,
        angle_deg=body.angle_deg,
        quarter_turns=0,
        taken_at=None,
        description="",
        album_id=stored.default_album_id or None,
        latitude=None,
        longitude=None,
        is_favorite=False,
        rating=None,
        visibility=stored.default_visibility or None,
        upload_status="pending",
        immich_asset_id=None,
        immich_status=None,
        album_linked=False,
        metadata_synced=False,
        uploaded_crop_signature=None,
        upload_error=None,
        uploaded_at=None,
        created_at=now,
        updated_at=now,
        **retouch_columns(stored),
    )
    session.add(region)
    session.flush()
    refresh_upload_state(session, scan)
    return region_out(region)


@router.patch("/{scan_id}/regions/{region_id}", response_model=RegionOut)
def update_region(
    scan_id: str,
    region_id: str,
    body: RegionPatch,
    session: Session = Depends(get_session),
) -> RegionOut:
    scan = _scan(session, scan_id)
    region = _region(session, scan, region_id)
    _apply_patch(scan, region, body)
    refresh_upload_state(session, scan)
    # The browser requests the new preview as soon as this response arrives.
    # Dependency cleanup can run after sending it, so commit the crop here.
    session.commit()
    return region_out(region)


@router.post("/{scan_id}/regions/{region_id}/rotate", response_model=RegionOut)
def rotate_region(
    scan_id: str,
    region_id: str,
    clockwise: bool = True,
    session: Session = Depends(get_session),
) -> RegionOut:
    region = _region(session, _scan(session, scan_id), region_id)
    region.quarter_turns = (region.quarter_turns + (1 if clockwise else 3)) % 4
    region.updated_at = utcnow()
    sync_retouch_status(region)
    return region_out(region)


@router.delete("/{scan_id}/regions/{region_id}", status_code=204)
def delete_region(
    scan_id: str,
    region_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> None:
    scan = _scan(session, scan_id)
    region = _region(session, scan, region_id)
    kept = [path for path in (region.crop_path, region.retouch_path) if path]
    session.delete(region)
    session.flush()
    refresh_upload_state(session, scan)
    for path in kept:
        services.storage.absolute(path).unlink(missing_ok=True)
    drop_previews(services, scan.id, region_id)


@router.post(
    "/{scan_id}/regions/{region_id}/retouch", response_model=RetouchQueued, status_code=202
)
def retouch_region(
    scan_id: str,
    region_id: str,
    body: RetouchRequest,
    session: Session = Depends(get_session),
) -> RetouchQueued:
    scan = _scan(session, scan_id)
    _require_files(scan)
    region = _region(session, scan, region_id)
    region.retouch_upscale = body.upscale
    region.retouch_denoise = body.denoise
    region.retouch_faces = body.faces
    region.retouch_colorize = body.colorize
    region.retouch_scratches = body.scratches
    region.retouch_color_balance = body.color_balance
    region.retouch_contrast = body.contrast
    region.retouch_dust = body.dust
    region.retouch_deblur = body.deblur
    region.retouch_gentle_denoise = body.gentle_denoise
    region.retouch_paper_mesh = body.paper_mesh
    region.retouch_paper_embossed = body.paper_embossed
    region.retouch_light_corners = body.light_corners
    region.retouch_output_scale = body.output_scale
    region.updated_at = utcnow()
    job = enqueue_job(
        session,
        job_type="retouch",
        scan_id=scan.id,
        region_id=region.id,
        payload={"scan_id": scan.id, "region_id": region.id},
    )
    region.retouch_status = "queued"
    region.retouch_error = None
    session.flush()
    return RetouchQueued(job_id=job.id, region=region_out(region))


@router.get("/{scan_id}/regions/{region_id}/retouch-preview")
def preview_retouch(
    scan_id: str,
    region_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> FileResponse:
    scan = _scan(session, scan_id)
    region = _region(session, scan, region_id)
    try:
        path = retouch_preview(services, scan, region)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{scan_id}/regions/{region_id}/preview")
def preview_region(
    scan_id: str,
    region_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> FileResponse:
    scan = _scan(session, scan_id)
    region = _region(session, scan, region_id)
    try:
        path = region_preview(services, scan, region)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/jpeg")


@router.post("/{scan_id}/regions/{region_id}/refresh-immich", response_model=RegionOut)
def refresh_immich_metadata(
    scan_id: str,
    region_id: str,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> RegionOut:
    region = _region(session, _scan(session, scan_id), region_id)
    if not region.immich_asset_id:
        raise HTTPException(status_code=409, detail="Photo has not been uploaded to Immich")
    if region.upload_status == "uploading":
        raise HTTPException(status_code=409, detail="Photo is uploading")
    settings = load_settings(session)
    try:
        gateway = services.build_gateway(settings.immich_base_url, settings.immich_api_key)
        try:
            details = gateway.get_asset(region.immich_asset_id)
        finally:
            gateway.close()
        metadata = details.metadata
        values = RegionPatch(
            taken_at=metadata.date_time_original,
            description=metadata.description,
            latitude=metadata.latitude,
            longitude=metadata.longitude,
            is_favorite=metadata.is_favorite,
            rating=metadata.rating if metadata.rating not in (0, -1) else None,
            visibility=metadata.visibility,
        )
    except (ImmichError, ValidationError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not refresh from Immich: {exc}"
        ) from exc
    region.taken_at = values.taken_at
    region.description = values.description or ""
    region.latitude = values.latitude
    region.longitude = values.longitude
    region.is_favorite = bool(values.is_favorite)
    region.rating = values.rating
    region.visibility = values.visibility
    region.album_id = details.album_ids[0] if details.album_ids else None
    region.album_linked = bool(region.album_id)
    region.metadata_synced = True
    region.updated_at = utcnow()
    session.flush()
    return region_out(region)


def _apply_patch(scan: Scan, region: Region, body: RegionPatch) -> None:
    fields = body.model_fields_set
    metadata_before = {name: getattr(region, name) for name in _META_FIELDS | {"album_id"}}
    geometry = {"center_x", "center_y", "width", "height", "angle_deg"}
    if geometry <= fields:
        ensure_geometry(
            scan,
            center_x=body.center_x,  # type: ignore[arg-type]
            center_y=body.center_y,  # type: ignore[arg-type]
            width=body.width,  # type: ignore[arg-type]
            height=body.height,  # type: ignore[arg-type]
            angle_deg=body.angle_deg,  # type: ignore[arg-type]
        )
        region.center_x = body.center_x  # type: ignore[assignment]
        region.center_y = body.center_y  # type: ignore[assignment]
        region.width = body.width  # type: ignore[assignment]
        region.height = body.height  # type: ignore[assignment]
        region.angle_deg = body.angle_deg  # type: ignore[assignment]
    if "quarter_turns" in fields and body.quarter_turns is not None:
        region.quarter_turns = body.quarter_turns
    if "taken_at" in fields:
        region.taken_at = body.taken_at
    if "description" in fields:
        region.description = body.description or ""
    if "album_id" in fields and region.album_id != body.album_id:
        region.album_linked = False
        region.album_id = body.album_id
    elif "album_id" in fields:
        region.album_id = body.album_id
    if "latitude" in fields:
        region.latitude = body.latitude
        region.longitude = body.longitude
    if "is_favorite" in fields and body.is_favorite is not None:
        region.is_favorite = body.is_favorite
    if "rating" in fields:
        region.rating = body.rating
    if "visibility" in fields:
        region.visibility = body.visibility
    metadata_changed = any(
        getattr(region, name) != value for name, value in metadata_before.items()
    )
    if metadata_changed:
        region.metadata_synced = False
        if region.upload_status != "uploading":
            region.upload_status = "pending"
            region.upload_error = None
    for name in (
        "retouch_upscale",
        "retouch_denoise",
        "retouch_faces",
        "retouch_colorize",
        "retouch_scratches",
        "retouch_color_balance",
        "retouch_contrast",
        "retouch_dust",
        "retouch_deblur",
        "retouch_gentle_denoise",
        "retouch_paper_mesh",
        "retouch_paper_embossed",
        "retouch_light_corners",
        "retouch_output_scale",
    ):
        if name in fields and getattr(body, name) is not None:
            setattr(region, name, getattr(body, name))
    if fields & _RETOUCH_FIELDS:
        sync_retouch_status(region)
    if "upload_source" in fields and body.upload_source is not None:
        if body.upload_source == "retouch" and not retouch_is_current(region):
            raise HTTPException(
                status_code=409,
                detail="Retouch this photo before uploading that version.",
            )
        region.upload_source = body.upload_source
    region.updated_at = utcnow()


def _scan(session: Session, scan_id: str) -> Scan:
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return scan


def _region(session: Session, scan: Scan, region_id: str) -> Region:
    region = session.get(Region, region_id)
    if region is None or region.scan_id != scan.id:
        raise HTTPException(status_code=404, detail="region not found")
    return region


def _require_files(scan: Scan) -> None:
    if scan.files_deleted or not scan.original_path:
        raise HTTPException(status_code=409, detail="scan files were deleted")


def _media_type(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix, "application/octet-stream")
