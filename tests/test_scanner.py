import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.scanner.base import ScannerError, ScanRequest
from app.scanner.commands import build_scan_command, parse_device_list
from app.scanner.fake import FakeScanner
from app.scanner.sane import SaneScanner


def test_parse_device_list_reads_sane_output() -> None:
    output = (
        "device `genesys:libusb:002:006' is a Canon LiDE 700F flatbed scanner\n"
        "device `test:0' is a Virtual scanner\n"
        "noise that is not a device line\n"
    )
    devices = parse_device_list(output)
    assert [device.name for device in devices] == ["genesys:libusb:002:006", "test:0"]
    assert devices[0].description == "Canon LiDE 700F flatbed scanner"


def test_full_bed_command_omits_geometry() -> None:
    request = ScanRequest(
        device_name="genesys:libusb:002:006",
        resolution_dpi=600,
        image_format="tiff",
        mode="Color",
    )
    command = build_scan_command(request, Path("/data/captures/last-scan.tif"))
    assert command == [
        "scanimage",
        "--format=tiff",
        "--resolution=600",
        "--mode=Color",
        "--output-file=/data/captures/last-scan.tif",
        "--device-name",
        "genesys:libusb:002:006",
    ]


def test_optional_window_is_passed_in_millimetres() -> None:
    request = ScanRequest(
        resolution_dpi=300,
        image_format="png",
        mode="Gray",
        width_mm=216,
        height_mm=297.5,
    )
    command = build_scan_command(request, Path("bed.png"))
    assert "--device-name" not in command
    assert command[command.index("-x") + 1] == "216"
    assert command[command.index("-y") + 1] == "297.5"


def test_list_devices_uses_scanimage() -> None:
    calls: list[list[str]] = []

    def runner(command, **_kwargs):  # type: ignore[no-untyped-def]
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
    def runner(command, **_kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="device busy")

    scanner = SaneScanner(runner=runner)
    destination = tmp_path / "bed.tif"
    with pytest.raises(ScannerError, match="device busy"):
        scanner.scan(
            ScanRequest(resolution_dpi=300, image_format="tiff", mode="Color"),
            destination,
        )


def test_fake_scanner_writes_a_tagged_image(tmp_path: Path) -> None:
    destination = tmp_path / "bed.tif"
    FakeScanner().scan(
        ScanRequest(resolution_dpi=300, image_format="tiff", mode="Color"),
        destination,
    )
    with Image.open(destination) as image:
        assert image.size == (1200, 1700)
        assert image.mode == "RGB"
        assert image.info["dpi"][0] == 300
