import hashlib
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.detection.base import DetectedRegion
from app.detection.opencv_detector import overlap_fraction
from app.imaging.crop import upright_crop
from app.imaging.exif_data import build_exif, format_immich_datetime
from app.imaging.io import load_rgb, save_rgb
from app.immich.gateway import AssetMetadata, ImmichError, PhotoUpload
from app.models import Region, Scan
from app.retouch.options import content_signature, retouch_is_current
from app.runtime import Services
from app.settings_store import load_settings, retouch_columns

logger = logging.getLogger(__name__)


def handle_detect(session: Session, job, services: Services) -> None:
    scan = session.get(Scan, job.scan_id) if job.scan_id else None
    if scan is None or scan.files_deleted or not scan.original_path:
        return
    image, embedded_dpi = load_rgb(services.storage.absolute(scan.original_path))
    if scan.dpi is None and embedded_dpi:
        scan.dpi = embedded_dpi
    try:
        detected = services.detector.detect(image)
    except Exception as exc:
        scan.detection_error = f"{type(exc).__name__}: {exc}"[:2000]
        session.commit()
        raise
    scan.detection_error = None
    _replace_open_regions(session, scan, detected)
    refresh_upload_state(session, scan)
    logger.info("detected %s photo(s) on scan %s", len(detected), scan.id)


def handle_upload(session: Session, job, services: Services) -> None:
    payload = json.loads(job.payload or "{}")
    scan_id = str(payload.get("scan_id") or job.scan_id or "")
    scan = session.get(Scan, scan_id)
    if scan is None or scan.files_deleted or not scan.original_path:
        raise RuntimeError("scan file is not available")
    regions = list(
        session.scalars(select(Region).where(Region.scan_id == scan.id).order_by(Region.position))
    )
    requested = payload.get("region_ids")
    if isinstance(requested, list) and requested:
        wanted = {str(item) for item in requested}
        regions = [region for region in regions if region.id in wanted]
    else:
        regions = [region for region in regions if needs_upload(region)]
    if not regions:
        refresh_upload_state(session, scan)
        return
    stored = load_settings(session)
    if not stored.immich_base_url or not stored.immich_api_key:
        raise ImmichError("Immich URL and API key are required")
    image, _dpi = load_rgb(services.storage.absolute(scan.original_path))
    gateway = services.build_gateway(stored.immich_base_url, stored.immich_api_key)
    errors: list[str] = []
    try:
        for region in regions:
            region_id = region.id
            try:
                _upload_region(session, services, gateway, scan, region, image, stored)
                session.commit()
            except Exception as exc:
                session.rollback()
                failed = session.get(Region, region_id)
                if failed is not None:
                    failed.upload_status = "failed"
                    failed.upload_error = f"{type(exc).__name__}: {exc}"[:2000]
                    failed.updated_at = utcnow()
                    session.commit()
                errors.append(f"{region_id}: {exc}")
    finally:
        gateway.close()
    current = session.get(Scan, scan.id)
    if current is not None:
        refresh_upload_state(session, current)
        session.commit()
    if errors:
        raise RuntimeError("; ".join(errors))


def needs_upload(region: Region) -> bool:
    signature = content_signature(region)
    if region.upload_status in {"pending", "failed", "uploading"}:
        return True
    if region.uploaded_crop_signature and region.uploaded_crop_signature != signature:
        return True
    if not region.metadata_synced:
        return True
    return bool(region.album_id) and not region.album_linked


def refresh_upload_state(session: Session, scan: Scan) -> None:
    regions = list(session.scalars(select(Region).where(Region.scan_id == scan.id)))
    uploaded = [region for region in regions if region.upload_status == "uploaded"]
    if regions and len(uploaded) == len(regions):
        scan.upload_state = "complete"
    elif uploaded:
        scan.upload_state = "partial"
    else:
        scan.upload_state = "pending"


def _replace_open_regions(session: Session, scan: Scan, detected) -> None:
    existing = list(session.scalars(select(Region).where(Region.scan_id == scan.id)))
    for region in existing:
        if region.upload_status != "uploaded":
            session.delete(region)
    session.flush()
    remaining = list(session.scalars(select(Region).where(Region.scan_id == scan.id)))
    kept = [
        DetectedRegion(
            center_x=region.center_x,
            center_y=region.center_y,
            width=region.width,
            height=region.height,
            angle_deg=region.angle_deg,
        )
        for region in remaining
    ]
    fresh = [item for item in detected if all(overlap_fraction(item, old) < 0.5 for old in kept)]
    start = max((region.position for region in remaining), default=0)
    stored = load_settings(session)
    default_album = stored.default_album_id or None
    now = utcnow()
    for offset, item in enumerate(fresh, start=1):
        session.add(
            Region(
                id=_new_id(),
                scan_id=scan.id,
                position=start + offset,
                center_x=item.center_x,
                center_y=item.center_y,
                width=item.width,
                height=item.height,
                angle_deg=item.angle_deg,
                quarter_turns=0,
                taken_at=None,
                description="",
                album_id=default_album,
                latitude=None,
                longitude=None,
                is_favorite=False,
                rating=None,
                visibility=None,
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
        )


def _upload_region(session, services, gateway, scan, region, image, stored) -> None:
    region.upload_status = "uploading"
    region.upload_error = None
    region.updated_at = utcnow()
    session.commit()
    signature = content_signature(region)
    content_changed = region.immich_asset_id is None or region.uploaded_crop_signature != signature
    if content_changed:
        cropped, output_dpi = _pixels_for_upload(services, scan, region, image)
        taken = region.taken_at if isinstance(region.taken_at, datetime) else None
        exif = build_exif(
            taken_at=taken,
            latitude=region.latitude,
            longitude=region.longitude,
            description=region.description,
        )
        extension = "jpg" if stored.output_format == "jpeg" else "png"
        content_type = "image/jpeg" if extension == "jpg" else "image/png"
        relative = f"scans/{scan.id}/outputs/{region.id}.{extension}"
        target = services.storage.absolute(relative)
        save_rgb(
            cropped,
            target,
            stored.output_format,
            jpeg_quality=stored.jpeg_quality,
            exif=exif,
            dpi=output_dpi,
        )
        content = target.read_bytes()
        stamp = format_immich_datetime(taken or datetime.now(UTC))
        result = gateway.upload_asset(
            PhotoUpload(
                filename=f"scan-{scan.id[:8]}-{region.position:02d}.{extension}",
                content=content,
                content_type=content_type,
                file_created_at=stamp,
                file_modified_at=stamp,
                sha1=hashlib.sha1(content).hexdigest(),
            )
        )
        region.immich_asset_id = result.id
        region.immich_status = result.status
        region.uploaded_crop_signature = signature
        region.album_linked = False
        region.metadata_synced = False
        session.commit()
    if region.album_id and not region.album_linked:
        if not region.immich_asset_id:
            raise ImmichError("asset id missing before album update")
        gateway.add_assets_to_album(region.album_id, [region.immich_asset_id])
        region.album_linked = True
    if not region.metadata_synced:
        if not region.immich_asset_id:
            raise ImmichError("asset id missing before metadata update")
        taken = region.taken_at if isinstance(region.taken_at, datetime) else None
        gateway.update_asset(
            region.immich_asset_id,
            AssetMetadata(
                description=region.description or "",
                is_favorite=region.is_favorite,
                date_time_original=format_immich_datetime(taken) if taken else None,
                latitude=region.latitude,
                longitude=region.longitude,
                rating=region.rating,
                visibility=region.visibility,
            ),
        )
        region.metadata_synced = True
    region.upload_status = "uploaded"
    region.uploaded_at = utcnow()
    region.upload_error = None
    region.updated_at = utcnow()


def _pixels_for_upload(services, scan: Scan, region: Region, image):
    if region.upload_source != "retouch":
        cropped = upright_crop(
            image,
            region.center_x,
            region.center_y,
            region.width,
            region.height,
            region.angle_deg,
            region.quarter_turns,
        )
        return cropped, scan.dpi
    if not retouch_is_current(region) or not region.retouch_path:
        raise RuntimeError(
            "The retouched version is not ready for this crop. "
            "Run retouch again, or upload the original."
        )
    derivative, _dpi = load_rgb(services.storage.absolute(region.retouch_path))
    return derivative, _scaled_dpi(scan, region, derivative)


def _scaled_dpi(scan: Scan, region: Region, derivative) -> int | None:
    """A current derivative was made from this geometry, so its crop width is known."""

    if not scan.dpi:
        return scan.dpi
    crop_w = max(1, int(round(region.width)))
    crop_h = max(1, int(round(region.height)))
    upright_w = crop_h if region.quarter_turns % 2 else crop_w
    scale = derivative.shape[1] / upright_w
    return max(1, int(round(scan.dpi * scale)))


def _new_id() -> str:
    from uuid import uuid4

    return str(uuid4())
