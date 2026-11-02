import subprocess
from collections.abc import Callable
from pathlib import Path

from app.scanner.base import ScannerDevice, ScannerError, ScanRequest
from app.scanner.commands import build_scan_command, parse_device_list

Runner = Callable[..., subprocess.CompletedProcess[str]]


class SaneScanner:
    """Drive a USB flatbed through the SANE `scanimage` command."""

    def __init__(
        self,
        runner: Runner | None = None,
        list_timeout: float = 15,
        scan_timeout: float = 600,
    ) -> None:
        self._run = runner or subprocess.run
        self._list_timeout = list_timeout
        self._scan_timeout = scan_timeout

    def list_devices(self) -> list[ScannerDevice]:
        try:
            completed = self._run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=self._list_timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ScannerError("scanimage is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise ScannerError("scanimage -L timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "scanimage -L failed").strip()
            raise ScannerError(detail)
        return parse_device_list(completed.stdout)

    def scan(self, request: ScanRequest, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = build_scan_command(request, destination)
        try:
            completed = self._run(
                command,
                capture_output=True,
                text=True,
                timeout=self._scan_timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ScannerError("scanimage is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise ScannerError("scan timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "scanimage failed").strip()
            raise ScannerError(detail)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ScannerError("scanimage exited without writing an image")
