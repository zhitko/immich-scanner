import re
from pathlib import Path

from app.scanner.base import ScannerDevice, ScanRequest

_DEVICE_LINE = re.compile(r"device `([^']+)' is a (.+)$")


def build_scan_command(request: ScanRequest, destination: Path) -> list[str]:
    """Build a `scanimage` argv that captures the whole bed unless size is set.

    Omitting `-x` and `-y` leaves the backend's default geometry, which for a
    flatbed is the full scan area. Pass millimetres only when the operator
    wants a smaller window.
    """

    command = [
        "scanimage",
        f"--format={request.image_format}",
        f"--resolution={request.resolution_dpi}",
        f"--mode={request.mode}",
        "--depth=16",
        f"--output-file={destination}",
    ]
    if request.device_name:
        command.extend(["--device-name", request.device_name])
    if request.width_mm is not None:
        command.extend(["-x", _format_mm(request.width_mm)])
    if request.height_mm is not None:
        command.extend(["-y", _format_mm(request.height_mm)])
    return command


def parse_device_list(output: str) -> list[ScannerDevice]:
    devices: list[ScannerDevice] = []
    for raw_line in output.splitlines():
        match = _DEVICE_LINE.search(raw_line.strip())
        if match is None:
            continue
        devices.append(ScannerDevice(name=match.group(1), description=match.group(2).strip()))
    return devices


def _format_mm(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
