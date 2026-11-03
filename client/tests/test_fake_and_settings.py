from pathlib import Path

from PIL import Image

from app.scanner.base import ScanRequest
from app.scanner.fake import FakeScanner
from app.schemas import ClientSettings
from app.state_store import LastScan, StateStore


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


def test_settings_round_trip(tmp_path: Path) -> None:
    store = StateStore(
        tmp_path,
        ClientSettings(server_url="http://archive.local:8080", api_token="seed"),
    )
    loaded = store.read_settings()
    assert loaded.api_token == "seed"
    store.write_settings(loaded.model_copy(update={"resolution_dpi": 600, "device_name": "fake:0"}))
    again = StateStore(tmp_path, ClientSettings())
    assert again.read_settings().resolution_dpi == 600
    assert again.read_settings().device_name == "fake:0"
    store.write_last_scan(LastScan(ok=True, message="Uploaded", scan_id="abc"))
    assert store.read_last_scan().scan_id == "abc"
