"""In-memory retouch percent, keyed by region. The desk polls the scan for it."""

import threading

_PROGRESS: dict[str, int] = {}
_GUARD = threading.Lock()


def set_retouch_progress(region_id: str, percent: int) -> None:
    shown = max(0, min(100, int(percent)))
    with _GUARD:
        _PROGRESS[region_id] = shown


def retouch_progress(region_id: str) -> int | None:
    with _GUARD:
        return _PROGRESS.get(region_id)


def clear_retouch_progress(region_id: str) -> None:
    with _GUARD:
        _PROGRESS.pop(region_id, None)
