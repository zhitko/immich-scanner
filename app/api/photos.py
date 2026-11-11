from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Region, Scan
from app.schemas import PhotoOut, ScanDetail
from app.serialize import region_out, scan_summary
from app.settings_store import apply_processing_defaults, load_settings

router = APIRouter(prefix="/photos", tags=["photos"])


@router.get("", response_model=list[PhotoOut])
def list_photos(
    state: Literal["open", "uploaded", "all"] = "open",
    filters: Annotated[
        list[Literal["original", "retouched", "has-date", "no-date"]] | None, Query()
    ] = None,
    session: Session = Depends(get_session),
) -> list[PhotoOut]:
    filters = filters or []
    query = (
        select(Region, Scan)
        .join(Scan, Region.scan_id == Scan.id)
        .order_by(Scan.created_at.desc(), Scan.id, Region.position)
    )
    if state == "uploaded":
        query = query.where(Region.upload_status == "uploaded")
    elif state == "open":
        query = query.where(Region.upload_status != "uploaded")
    dates = set(filters) & {"has-date", "no-date"}
    if dates == {"has-date"}:
        query = query.where(Region.taken_at.is_not(None))
    elif dates == {"no-date"}:
        query = query.where(Region.taken_at.is_(None))
    versions = set(filters) & {"original", "retouched"}
    photos = []
    for region, scan in session.execute(query):
        photo = region_out(region)
        if len(versions) == 1:
            version = "retouched" if photo.retouch_ready else "original"
            if version not in versions:
                continue
        photos.append(
            PhotoOut(
                **photo.model_dump(),
                scan_id=scan.id,
                created_at=scan.created_at,
                files_deleted=scan.files_deleted,
                dpi=scan.dpi,
            )
        )
    return photos


@router.get("/{photo_id}", response_model=ScanDetail)
def get_photo(
    photo_id: str,
    apply_defaults: bool = False,
    session: Session = Depends(get_session),
) -> ScanDetail:
    region = session.get(Region, photo_id)
    if region is None:
        raise HTTPException(status_code=404, detail="photo not found")
    scan = session.get(Scan, region.scan_id)
    if apply_defaults and not scan.files_deleted:
        apply_processing_defaults(region, load_settings(session))
        session.commit()
    return ScanDetail(
        **scan_summary(session, scan).model_dump(),
        regions=[region_out(region)],
    )
