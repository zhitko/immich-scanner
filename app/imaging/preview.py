import hashlib
from pathlib import Path

from app.imaging.crop import apply_quarter_turns, crop_rotated_rect, crop_signature, resize_max_edge
from app.imaging.io import load_rgb, save_rgb
from app.models import Region, Scan
from app.runtime import Services


def region_preview(services: Services, scan: Scan, region: Region) -> Path:
    if scan.files_deleted or not scan.original_path:
        raise FileNotFoundError("scan files were deleted")
    signature = crop_signature(
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
        region.quarter_turns,
    )
    digest = hashlib.sha1(signature.encode()).hexdigest()[:16]
    relative = f"scans/{scan.id}/previews/{region.id}-{digest}.jpg"
    path = services.storage.absolute(relative)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob(f"{region.id}-*.jpg"):
        old.unlink()
    image, _dpi = load_rgb(services.storage.absolute(scan.original_path))
    cropped = crop_rotated_rect(
        image,
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
    )
    cropped = apply_quarter_turns(cropped, region.quarter_turns)
    save_rgb(resize_max_edge(cropped, 1000), path, "jpeg", jpeg_quality=82)
    return path
