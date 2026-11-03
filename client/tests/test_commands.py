from pathlib import Path

from app.scanner.base import ScanRequest
from app.scanner.commands import build_scan_command, parse_device_list


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
