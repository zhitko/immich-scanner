from fastapi import HTTPException

from app.models import Scan


def ensure_geometry(
    scan: Scan,
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
) -> None:
    if width < 8 or height < 8:
        raise HTTPException(status_code=422, detail="region is too small")
    if width > scan.width * 2 or height > scan.height * 2:
        raise HTTPException(status_code=422, detail="region is larger than the scan")
    if not (0 <= center_x <= scan.width and 0 <= center_y <= scan.height):
        raise HTTPException(status_code=422, detail="region center is outside the scan")
    if not -180 <= angle_deg <= 180:
        raise HTTPException(status_code=422, detail="angle is out of range")
