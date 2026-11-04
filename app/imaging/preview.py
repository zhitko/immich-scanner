import hashlib
import os
import threading
import time
from pathlib import Path

import numpy as np

from app.imaging.crop import crop_rotated_rect, crop_signature, resize_max_edge
from app.imaging.io import load_rgb, save_rgb
from app.models import Region, Scan
from app.runtime import Services

# Leave a fresh sibling in place long enough for its response to open the file.
_KEEP_SECONDS = 60.0

_cache_lock = threading.Lock()
_cached: tuple[Path, float, np.ndarray] | None = None
_region_locks_guard = threading.Lock()
_region_locks: dict[str, threading.Lock] = {}


def region_preview(services: Services, scan: Scan, region: Region) -> Path:
    if scan.files_deleted or not scan.original_path:
        raise FileNotFoundError("scan files were deleted")
    # Quarter turns are drawn in the editor. Baking them in made the preview
    # wait on a new JPEG, so a click looked like it did nothing until reload.
    path = _preview_path(services, scan, region)
    if path.is_file():
        return path
    with _region_lock(region.id):
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
        partial = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        save_rgb(resize_max_edge(cropped, 1000), partial, "jpeg", jpeg_quality=82)
        os.replace(partial, path)
        _drop_expired(path, region.id)
    return path


def _preview_path(services: Services, scan: Scan, region: Region) -> Path:
    signature = crop_signature(
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
        0,
    )
    digest = hashlib.sha1(signature.encode()).hexdigest()[:16]
    return services.storage.absolute(f"scans/{scan.id}/previews/{region.id}-{digest}.jpg")


def _region_lock(region_id: str) -> threading.Lock:
    with _region_locks_guard:
        lock = _region_locks.get(region_id)
        if lock is None:
            lock = threading.Lock()
            _region_locks[region_id] = lock
        return lock


def _drop_expired(path: Path, region_id: str) -> None:
    cutoff = time.time() - _KEEP_SECONDS
    for old in path.parent.glob(f"{region_id}-*.jpg"):
        if old == path:
            continue
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        except OSError:
            continue


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
