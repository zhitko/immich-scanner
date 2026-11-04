from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.imaging.crop import crop_signature
from app.models import Region, Scan
from app.schemas import RegionOut, ScanDetail, ScanSummary


def region_out(region: Region) -> RegionOut:
    signature = crop_signature(
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
        region.quarter_turns,
    )
    changed = bool(region.uploaded_crop_signature) and region.uploaded_crop_signature != signature
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
        updated_at=region.updated_at,
    )


def scan_summary(session: Session, scan: Scan) -> ScanSummary:
    counts = session.execute(
        select(
            func.count(Region.id),
            func.count(Region.id).filter(Region.upload_status == "uploaded"),
        ).where(Region.scan_id == scan.id)
    ).one()
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
