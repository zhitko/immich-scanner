import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.intake import IntakeError, register_scan
from app.runtime import Services
from app.scanner.base import Scanner, ScannerDevice, ScannerError, ScanRequest
from app.schemas import ScannerDeviceOut, ScannerStatusOut
from app.settings_store import load_settings

logger = logging.getLogger(__name__)

_PROBE_TTL_S = 10
_DEVICE_WAIT_S = 30
_BUSY_RETRIES = 3
_BUSY_DELAY_S = 3.0


class BedScan:
    """Capture one bed at a time, then hand the image to detection.

    SANE devices can only be opened by one process, so listing and scanning
    share `_device_lock`. Status polls never wait for it; they answer from the
    last probe while the device is in use.
    """

    def __init__(self, services: Services, scanner: Scanner) -> None:
        self._services = services
        self.scanner = scanner
        self._lock = threading.Lock()
        self._device_lock = threading.Lock()
        self._phase = "idle"
        self._phase_message = "Idle"
        self._phase_started_at: datetime | None = None
        self._thread: threading.Thread | None = None
        self._scanner_cache: tuple[float, bool, str, list[ScannerDevice]] | None = None
        self._last_ok: bool | None = None
        self._last_message = ""
        self._last_id: str | None = None
        self.busy_delay_s = _BUSY_DELAY_S

    def status(self) -> ScannerStatusOut:
        found, message, devices = self._scanner_probe()
        with self._lock:
            return ScannerStatusOut(
                phase=self._phase,  # type: ignore[arg-type]
                phase_message=self._phase_message,
                phase_started_at=self._phase_started_at,
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
            self._phase_started_at = datetime.now(UTC)
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
        self._finish(ok=True, message="Scan saved. Detecting photos.", scan_id=scan_id)

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
        if not self._device_lock.acquire(timeout=_DEVICE_WAIT_S):
            raise ScannerError("the scanner is still in use by a device check")
        try:
            self._scan_with_retry(request, destination)
        finally:
            self._device_lock.release()
        self._set_phase("saving", "Saving the scan")
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

    def _scan_with_retry(self, request: ScanRequest, destination: Path) -> None:
        for attempt in range(1, _BUSY_RETRIES + 1):
            try:
                self.scanner.scan(request, destination)
                return
            except ScannerError as exc:
                if "busy" not in str(exc).lower() or attempt == _BUSY_RETRIES:
                    raise
                logger.info("scanner busy, retrying (%s/%s)", attempt, _BUSY_RETRIES)
                self._set_phase("scanning", "Scanner is busy, trying again")
                time.sleep(self.busy_delay_s)
                self._set_phase("scanning", "Scanning the bed")

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
            self._phase_started_at = None

    def _set_phase(self, phase: str, message: str) -> None:
        with self._lock:
            if phase != self._phase:
                self._phase_started_at = datetime.now(UTC)
            self._phase = phase
            self._phase_message = message

    def _scanner_probe(self) -> tuple[bool, str, list[ScannerDevice]]:
        now = time.monotonic()
        with self._lock:
            cached = self._scanner_cache
            busy = self._phase != "idle"
        if cached is not None and (busy or now - cached[0] < _PROBE_TTL_S):
            return cached[1], cached[2], cached[3]
        if busy or not self._device_lock.acquire(blocking=False):
            if cached is not None:
                return cached[1], cached[2], cached[3]
            return False, "Checking the scanner…", []
        try:
            listed = self.scanner.list_devices()
        except ScannerError as exc:
            found = False
            message = str(exc)
            devices: list[ScannerDevice] = []
        else:
            devices = listed
            found = bool(devices)
            if len(devices) == 1:
                message = devices[0].description
            elif devices:
                message = f"{len(devices)} scanners"
            else:
                message = "No scanner found. Check the USB cable and power."
        finally:
            self._device_lock.release()
        with self._lock:
            self._scanner_cache = (time.monotonic(), found, message, devices)
        return found, message, devices
