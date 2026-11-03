import subprocess
from pathlib import Path

import pytest

from app.scanner.base import ScannerError, ScanRequest
from app.scanner.sane import SaneScanner


def test_list_devices_uses_scanimage() -> None:
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="device `genesys:libusb:001:004' is a Canon LiDE 700F flatbed scanner\n",
            stderr="",
        )

    scanner = SaneScanner(runner=runner)
    devices = scanner.list_devices()
    assert calls == [["scanimage", "-L"]]
    assert devices[0].name == "genesys:libusb:001:004"


def test_scan_failure_raises(tmp_path: Path) -> None:
    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="device busy")

    scanner = SaneScanner(runner=runner)
    destination = tmp_path / "bed.tif"
    with pytest.raises(ScannerError, match="device busy"):
        scanner.scan(
            ScanRequest(resolution_dpi=300, image_format="tiff", mode="Color"),
            destination,
        )
