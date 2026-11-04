import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.intake import IntakeError, register_scan
from app.runtime import Services
from app.scanner.base import Scanner, ScannerDevice, ScannerError, ScanRequest
from app.schemas import ScannerDeviceOut, ScannerStatusOut
from app.settings_store import load_settings

logger = logging.getLogger(__name__)


class BedScan:
    """Capture one bed at a time, then hand the image to detection."""

    def __init__(self, services: Services, scanner: Scanner) -> None:
        self._services = services
        self.scanner = scanner
        self._lock = threading.Lock()
        self._phase = "idle"
        self._phase_message = "Idle"
        self._thread: threading.Thread | None = None
        self._probe_lock = threading.Lock()
        self._scanner_cache: tuple[float, bool, str, list[ScannerDevice]] | None = None
        self._last_ok: bool | None = None
        self._last_message = ""
        self._last_id: str | None = None

    def status(self) -> ScannerStatusOut:
        found, message, devices = self._scanner_probe()
        with self._lock:
            return ScannerStatusOut(
                phase=self._phase,  # type: ignore[arg-type]
                phase_message=self._phase_message,
                scanner_found=found,
                scanner_message=message,
                devices=[
                    ScannerDeviceOut(name=device.name, description=device.description)
                    for device in devices
                ],
                last_scan_ok=self._last_ok,
                last_scan_message=self._last_message,
                last_scan_id=self._last_id,
            )

    def start(self) -> None:
        with self._lock:
            if self._phase != "idle":
                raise RuntimeError("a scan is already running")
            self._phase = "scanning"
            self._phase_message = "Scanning the bed"
            self._thread = threading.Thread(target=self._run, name="scan", daemon=True)
            self._thread.start()

    def wait(self, timeout: float) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self) -> None:
        try:
            scan_id = self._capture()
        except (ScannerError, IntakeError, OSError) as exc:
            logger.info("scan failed: %s", exc)
            self._finish(ok=False, message=str(exc), scan_id=None)
            return
        except Exception as exc:
            logger.exception("scan failed")
            self._finish(ok=False, message=str(exc), scan_id=None)
            return
        self._finish(ok=True, message="Ready for review", scan_id=scan_id)

    def _capture(self) -> str:
        with self._services.session_factory() as session:
            settings = load_settings(session)
        extension = "png" if settings.scan_format == "png" else "tif"
        destination = self._capture_path(extension)
        request = ScanRequest(
            device_name=settings.device_name,
            resolution_dpi=settings.resolution_dpi,
            image_format=settings.scan_format,
            mode=settings.scan_mode,
            width_mm=settings.width_mm,
            height_mm=settings.height_mm,
        )
        self.scanner.scan(request, destination)
        self._set_phase("scanning", "Preparing the scan")
        session = self._services.session_factory()
        registered = None
        try:
            registered = register_scan(
                session,
                self._services,
                destination,
                dpi=settings.resolution_dpi,
                device_name=settings.device_name,
                filename=destination.name,
            )
            session.commit()
        except Exception:
            session.rollback()
            if registered is not None:
                self._services.storage.remove_tree(registered.scan_id)
            destination.unlink(missing_ok=True)
            raise
        finally:
            session.close()
        return registered.scan_id

    def _capture_path(self, extension: str) -> Path:
        directory = self._services.settings.data_dir / "captures"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{uuid4()}.{extension}"

    def _finish(self, *, ok: bool, message: str, scan_id: str | None) -> None:
        with self._lock:
            self._last_ok = ok
            self._last_message = message
            self._last_id = scan_id
            self._phase = "idle"
            self._phase_message = "Idle"

    def _set_phase(self, phase: str, message: str) -> None:
        with self._lock:
            self._phase = phase
            self._phase_message = message

    def _scanner_probe(self) -> tuple[bool, str, list[ScannerDevice]]:
        now = datetime.now(UTC).timestamp()
        with self._lock:
            scanning = self._phase == "scanning"
        with self._probe_lock:
            cached = self._scanner_cache
            if scanning:
                if cached is None:
                    return True, "Scanning", []
                return cached[1], "Scanning", cached[3]
            if cached is not None and now - cached[0] < 10:
                return cached[1], cached[2], cached[3]
        try:
            listed = self.scanner.list_devices()
        except ScannerError as exc:
            found = False
            message = str(exc)
            devices: list[ScannerDevice] = []
        else:
            devices = listed
            if devices:
                found = True
                message = f"{len(devices)} scanner(s) found"
            else:
                found = False
                message = "No scanner reported by the backend"
        with self._probe_lock:
            self._scanner_cache = (now, found, message, devices)
        return found, message, devices
