from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Region, Scan
from app.retouch.options import RetouchOptions, options_from_token
from app.schemas import StatisticsOut

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("", response_model=StatisticsOut)
def get_statistics(session: Session = Depends(get_session)) -> StatisticsOut:
    """Summarize all retained records, independently of scan-list pagination."""
    scans = (
        session.execute(
            select(
                func.count(Scan.id).label("scans"),
                func.count(Scan.id).filter(Scan.upload_state == "complete").label("scans_uploaded"),
                func.count(Scan.id).filter(Scan.files_deleted).label("scans_cleaned_up"),
                func.count(Scan.id)
                .filter(Scan.detection_error.is_not(None))
                .label("detection_errors"),
                func.min(Scan.created_at).label("first_scan_at"),
                func.max(Scan.created_at).label("latest_scan_at"),
            )
        )
        .one()
        ._mapping
    )
    photos = (
        session.execute(
            select(
                func.count(Region.id).label("photos"),
                func.count(Region.id).filter(Region.upload_status == "uploaded").label("uploaded"),
                func.count(Region.id).filter(Region.upload_status == "pending").label("pending"),
                func.count(Region.id)
                .filter(Region.upload_status == "uploading")
                .label("uploading"),
                func.count(Region.id).filter(Region.upload_status == "failed").label("failed"),
                func.count(Region.id).filter(Region.taken_at.is_not(None)).label("with_date"),
                func.count(Region.id)
                .filter(func.length(func.trim(Region.description, " \t\n\r")) > 0)
                .label("with_description"),
                func.count(Region.id)
                .filter(Region.album_id.is_not(None), Region.album_id != "")
                .label("with_album"),
                func.count(Region.id)
                .filter(Region.latitude.is_not(None), Region.longitude.is_not(None))
                .label("with_location"),
                func.count(Region.id).filter(Region.is_favorite).label("favorites"),
                func.count(Region.id).filter(Region.rating.is_not(None)).label("with_rating"),
                func.count(Region.id)
                .filter(Region.upload_status == "uploaded", Region.metadata_synced)
                .label("metadata_synced"),
                func.count(func.distinct(Region.album_id))
                .filter(Region.album_id != "")
                .label("albums"),
                func.min(Region.taken_at).label("earliest_photo_at"),
                func.max(Region.taken_at).label("latest_photo_at"),
                func.max(Region.uploaded_at).label("latest_upload_at"),
            )
        )
        .one()
        ._mapping
    )
    retouches = {
        "retouched": 0,
        **{f"retouched_{step}": 0 for step in RetouchOptions.__dataclass_fields__},
    }
    # A signature is saved only after a successful retouch. Current switches may
    # describe a later edit or retry, so read the steps from the completed result.
    results = session.execute(
        select(Region.retouch_signature, func.count(Region.id))
        .where(Region.retouch_signature.is_not(None), Region.retouch_signature != "")
        .group_by(Region.retouch_signature)
    )
    for signature, count in results:
        retouches["retouched"] += count
        options = options_from_token(signature.rpartition("|")[2])
        if options is not None:
            for step in RetouchOptions.__dataclass_fields__:
                if getattr(options, step):
                    retouches[f"retouched_{step}"] += count
    return StatisticsOut(**scans, **photos, **retouches)
