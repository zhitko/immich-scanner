import hashlib
import os
import threading
from pathlib import Path

import numpy as np

from app.imaging.crop import apply_quarter_turns, crop_rotated_rect, crop_signature, resize_max_edge
from app.imaging.io import load_rgb, save_rgb
from app.models import Region, Scan
from app.runtime import Services

_cache_lock = threading.Lock()
_cached: tuple[Path, float, np.ndarray] | None = None


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
    image = _original(services.storage.absolute(scan.original_path))
    cropped = crop_rotated_rect(
        image,
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
    )
    cropped = apply_quarter_turns(cropped, region.quarter_turns)
    partial = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    save_rgb(resize_max_edge(cropped, 1000), partial, "jpeg", jpeg_quality=82)
    os.replace(partial, path)
    for old in path.parent.glob(f"{region.id}-*.jpg"):
        if old != path:
            old.unlink(missing_ok=True)
    return path


def _original(path: Path) -> np.ndarray:
    """Keep the last decoded bed in memory; editing one scan reuses it per preview."""

    global _cached
    mtime = path.stat().st_mtime
    with _cache_lock:
        if _cached is not None and _cached[0] == path and _cached[1] == mtime:
            return _cached[2]
    image, _dpi = load_rgb(path)
    with _cache_lock:
        _cached = (path, mtime, image)
    return image
