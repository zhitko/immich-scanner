import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.scanner.base import Scanner, ScannerError, ScanRequest
from app.schemas import ClientSettings, DeviceOut, StatusOut
from app.state_store import LastScan, StateStore
from app.uploader import ScanUploader, UploadError

Phase = Literal["idle", "scanning", "uploading"]


class AgentService:
    """One scan at a time. Status probes are cached so the UI can poll cheaply."""

    def __init__(
        self,
        store: StateStore,
        scanner: Scanner,
        uploader: ScanUploader,
        data_dir: Path,
    ) -> None:
        self._store = store
        self._scanner = scanner
        self._uploader = uploader
        self._data_dir = data_dir
        self._lock = threading.Lock()
        self._phase: Phase = "idle"
        self._phase_message = "Idle"
        self._thread: threading.Thread | None = None
        self._probe_lock = threading.Lock()
        self._scanner_cache: tuple[float, bool, str, list[DeviceOut]] | None = None
        self._server_cache: tuple[float, str, bool, str] | None = None

    def status(self) -> StatusOut:
        settings = self._store.read_settings()
        last = self._store.read_last_scan()
        found, scanner_message, devices = self._scanner_probe()
        reachable, server_message = self._server_probe(settings.server_url)
        with self._lock:
            phase = self._phase
            phase_message = self._phase_message
        return StatusOut(
            phase=phase,
            phase_message=phase_message,
            scanner_found=found,
            scanner_message=scanner_message,
            devices=devices,
            server_reachable=reachable,
            server_message=server_message,
            last_scan_at=last.at,
            last_scan_ok=last.ok,
            last_scan_message=last.message,
            last_scan_id=last.scan_id,
        )

    def settings(self) -> ClientSettings:
        return self._store.read_settings()

    def update_settings(self, settings: ClientSettings) -> ClientSettings:
        saved = self._store.write_settings(settings)
        with self._probe_lock:
            self._server_cache = None
        return saved

    def start_scan(self) -> None:
        with self._lock:
            if self._phase != "idle":
                raise RuntimeError("a scan is already running")
            self._phase = "scanning"
            self._phase_message = "Scanning the full bed"
            self._thread = threading.Thread(target=self._scan_worker, name="scan", daemon=True)
            self._thread.start()

    def wait(self, timeout: float) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _scan_worker(self) -> None:
        settings = self._store.read_settings()
        extension = "png" if settings.image_format == "png" else "tif"
        destination = self._data_dir / "captures" / f"last-scan.{extension}"
        try:
            request = ScanRequest(
                device_name=settings.device_name,
                resolution_dpi=settings.resolution_dpi,
                image_format=settings.image_format,
                mode=settings.mode,
                width_mm=settings.width_mm,
                height_mm=settings.height_mm,
            )
            self._scanner.scan(request, destination)
            self._set_phase("uploading", "Uploading the bed image")
            scan_id = self._uploader.upload(
                server_url=settings.server_url,
                api_token=settings.api_token,
                image_path=destination,
                dpi=settings.resolution_dpi,
                device_name=settings.device_name,
                image_format=settings.image_format,
            )
            self._store.write_last_scan(
                LastScan(at=datetime.now(UTC), ok=True, message="Uploaded", scan_id=scan_id)
            )
        except (ScannerError, UploadError, OSError) as exc:
            self._store.write_last_scan(
                LastScan(at=datetime.now(UTC), ok=False, message=str(exc), scan_id=None)
            )
        finally:
            self._set_phase("idle", "Idle")

    def _set_phase(self, phase: Phase, message: str) -> None:
        with self._lock:
            self._phase = phase
            self._phase_message = message

    def _scanner_probe(self) -> tuple[bool, str, list[DeviceOut]]:
        now = datetime.now(UTC).timestamp()
        with self._probe_lock:
            cached = self._scanner_cache
            if cached is not None and now - cached[0] < 10:
                return cached[1], cached[2], cached[3]
        try:
            listed = self._scanner.list_devices()
        except ScannerError as exc:
            found = False
            message = str(exc)
            devices: list[DeviceOut] = []
        else:
            devices = [
                DeviceOut(name=device.name, description=device.description) for device in listed
            ]
            if devices:
                found = True
                message = f"{len(devices)} scanner(s) found"
            else:
                found = False
                message = "No scanner reported by the backend"
        with self._probe_lock:
            self._scanner_cache = (now, found, message, devices)
        return found, message, devices

    def _server_probe(self, server_url: str) -> tuple[bool, str]:
        now = datetime.now(UTC).timestamp()
        with self._probe_lock:
            cached = self._server_cache
            if cached is not None and cached[1] == server_url and now - cached[0] < 5:
                return cached[2], cached[3]
        if not server_url.strip():
            reachable = False
            message = "Server URL is empty"
        else:
            try:
                self._uploader.probe(server_url)
            except UploadError as exc:
                reachable = False
                message = str(exc)
            else:
                reachable = True
                message = "Reachable"
        with self._probe_lock:
            self._server_cache = (now, server_url, reachable, message)
        return reachable, message
