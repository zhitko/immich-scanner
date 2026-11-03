import json
from datetime import datetime
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ValidationError

from app.schemas import ClientSettings


class LastScan(BaseModel):
    at: datetime | None = None
    ok: bool | None = None
    message: str = ""
    scan_id: str | None = None


class StateStore:
    """JSON files on the data volume. The UI edits survive container restarts."""

    def __init__(self, data_dir: Path, defaults: ClientSettings) -> None:
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._settings_path = self._dir / "settings.json"
        self._last_scan_path = self._dir / "last-scan.json"
        self._lock = Lock()
        self._defaults = defaults
        if not self._settings_path.exists():
            self.write_settings(defaults)

    def read_settings(self) -> ClientSettings:
        with self._lock:
            return self._read_model(self._settings_path, ClientSettings, self._defaults)

    def write_settings(self, settings: ClientSettings) -> ClientSettings:
        with self._lock:
            self._write_model(self._settings_path, settings)
            return settings

    def read_last_scan(self) -> LastScan:
        with self._lock:
            return self._read_model(self._last_scan_path, LastScan, LastScan())

    def write_last_scan(self, last_scan: LastScan) -> LastScan:
        with self._lock:
            self._write_model(self._last_scan_path, last_scan)
            return last_scan

    @staticmethod
    def _read_model[T: BaseModel](path: Path, model: type[T], fallback: T) -> T:
        if not path.exists():
            return fallback
        try:
            return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError):
            return fallback

    @staticmethod
    def _write_model(path: Path, model: BaseModel) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
