"""In-memory retouch percent, keyed by region. The desk polls the scan for it."""

import threading

_PROGRESS: dict[str, tuple[int, str]] = {}
_GUARD = threading.Lock()


def set_retouch_progress(region_id: str, percent: int) -> None:
    shown = max(0, min(100, int(percent)))
    with _GUARD:
        _stage = _PROGRESS.get(region_id, (0, ""))[1]
        _PROGRESS[region_id] = (shown, _stage)


def set_retouch_stage(region_id: str, stage: str) -> None:
    with _GUARD:
        percent = _PROGRESS.get(region_id, (0, ""))[0]
        _PROGRESS[region_id] = (percent, stage)


def retouch_progress(region_id: str) -> int | None:
    with _GUARD:
        stored = _PROGRESS.get(region_id)
        return None if stored is None else stored[0]


def retouch_stage(region_id: str) -> str | None:
    with _GUARD:
        stored = _PROGRESS.get(region_id)
        if stored is None or not stored[1]:
            return None
        return stored[1]


def clear_retouch_progress(region_id: str) -> None:
    with _GUARD:
        _PROGRESS.pop(region_id, None)
