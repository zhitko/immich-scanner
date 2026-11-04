import time

import piexif

from app.immich.gateway import Album, AssetMetadata, AssetUploadResult, ImmichError, PhotoUpload
from app.intake import register_scan
from app.scanner.base import ScannerError
from app.scanner.fake import FakeScanner
from mock_immich.app import FAMILY_ALBUM
from tests.synthetic import encode_png, make_bed


class RecordingImmich:
    def __init__(self) -> None:
        self.uploads: list[PhotoUpload] = []
        self.album_adds: list[tuple[str, list[str]]] = []
        self.updates: list[tuple[str, AssetMetadata]] = []
        self.fail = False

    def server_version(self) -> str:
        return "3.3.5"

    def list_albums(self) -> list[Album]:
        return [Album(id=FAMILY_ALBUM, name="Family", asset_count=2)]

    def upload_asset(self, photo: PhotoUpload) -> AssetUploadResult:
        if self.fail:
            raise ImmichError("immich unavailable")
        self.uploads.append(photo)
        asset_id = f"00000000-0000-4000-8000-{len(self.uploads):012d}"
        return AssetUploadResult(id=asset_id, status="created")

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        self.album_adds.append((album_id, asset_ids))

    def update_asset(self, asset_id: str, metadata: AssetMetadata) -> None:
        self.updates.append((asset_id, metadata))

    def close(self) -> None:
        return None


def _import_bed(services, content: bytes, *, dpi: int = 300, filename: str = "bed.png") -> str:
    source = services.storage.root / "incoming" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    with services.session_factory() as session:
        registered = register_scan(
            session,
            services,
            source,
            dpi=dpi,
            device_name="fake:0",
            filename=filename,
        )
        session.commit()
    return registered.scan_id


def test_pipeline_detects_reviews_and_uploads(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1

    detail = client.get(f"/api/scans/{scan_id}").json()
    assert detail["region_count"] == 3
    assert detail["dpi"] == 300
    region_id = detail["regions"][0]["id"]
    patched = client.patch(
        f"/api/scans/{scan_id}/regions/{region_id}",
        json={
            "taken_at": "1999-01-02T03:04:05+00:00",
            "description": "Aunt Mae",
            "album_id": FAMILY_ALBUM,
            "latitude": 41.0,
            "longitude": -73.5,
            "is_favorite": True,
            "rating": 5,
            "visibility": "archive",
        },
    )
    assert patched.status_code == 200
    preview = client.get(f"/api/scans/{scan_id}/regions/{region_id}/preview")
    assert preview.status_code == 200
    assert preview.content.startswith(b"\xff\xd8")

    gateway = RecordingImmich()
    services.build_gateway = lambda _url, _key: gateway
    settings = client.put(
        "/api/settings",
        json={
            "immich_base_url": "http://immich.local:2283",
            "immich_api_key": "secret-key",
            "output_format": "jpeg",
            "jpeg_quality": 95,
            "default_album_id": "",
        },
    )
    assert settings.status_code == 200
    probe = client.post("/api/settings/test", json=settings.json())
    assert probe.status_code == 200
    assert probe.json()["version"] == "3.3.5"
    assert client.get("/api/immich/albums").json()[0]["name"] == "Family"

    assert client.post(f"/api/scans/{scan_id}/upload").status_code == 202
    assert app.state.worker.process_available() == 1
    uploaded = client.get(f"/api/scans/{scan_id}").json()
    assert uploaded["upload_state"] == "complete"
    assert len(gateway.uploads) == 3
    exif = piexif.load(gateway.uploads[0].content)
    assert exif["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"1999:01:02 03:04:05"
    assert gateway.album_adds[0][0] == FAMILY_ALBUM
    assert gateway.updates[0][1].description == "Aunt Mae"
    assert gateway.updates[0][1].is_favorite is True
    assert gateway.updates[0][1].latitude == 41.0

    archived = client.get("/api/scans", params={"state": "uploaded"}).json()
    assert archived[0]["id"] == scan_id
    assert client.get("/api/scans", params={"state": "open"}).json() == []
    kept = client.delete(f"/api/scans/{scan_id}/files")
    assert kept.status_code == 200
    assert kept.json()["files_deleted"] is True
    assert kept.json()["regions"][0]["immich_asset_id"]
    assert client.get(f"/api/scans/{scan_id}/original").status_code == 404
    jobs = client.get("/api/jobs").json()
    assert {job["status"] for job in jobs} == {"finished"}


def test_manual_region_rotate_and_retry(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(
        services,
        encode_png(make_bed(speck=False, photos=[])),
        dpi=200,
        filename="empty.png",
    )
    app.state.worker.process_available()
    detail = client.get(f"/api/scans/{scan_id}").json()
    assert detail["region_count"] == 0
    added = client.post(
        f"/api/scans/{scan_id}/regions",
        json={"center_x": 200, "center_y": 200, "width": 120, "height": 80, "angle_deg": 0},
    )
    assert added.status_code == 201
    region_id = added.json()["id"]
    rotated = client.post(f"/api/scans/{scan_id}/regions/{region_id}/rotate")
    assert rotated.json()["quarter_turns"] == 1

    gateway = RecordingImmich()
    gateway.fail = True
    services.build_gateway = lambda _url, _key: gateway
    client.put(
        "/api/settings",
        json={
            "immich_base_url": "http://immich.local:2283",
            "immich_api_key": "secret-key",
            "output_format": "png",
            "jpeg_quality": 95,
            "default_album_id": "",
        },
    )
    client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [region_id]})
    app.state.worker.process_available()
    failed = client.get(f"/api/scans/{scan_id}").json()
    assert failed["regions"][0]["upload_status"] == "failed"
    assert "immich unavailable" in failed["regions"][0]["upload_error"]
    assert client.get("/api/jobs", params={"status": "failed"}).json()

    gateway.fail = False
    client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [region_id]})
    app.state.worker.process_available()
    restored = client.get(f"/api/scans/{scan_id}").json()
    assert restored["regions"][0]["upload_status"] == "uploaded"
    assert gateway.uploads[0].content_type == "image/png"
    assert client.delete(f"/api/scans/{scan_id}/regions/{region_id}").status_code == 204
    assert client.get(f"/api/scans/{scan_id}").json()["region_count"] == 0


def test_migrations_can_run_twice(tmp_path) -> None:
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'archive.db'}",
        static_dir=tmp_path / "no-ui",
        scanner_backend="fake",
        worker_enabled=False,
    )
    first = create_app(settings)
    second = create_app(settings)
    first.state.services.engine.dispose()
    second.state.services.engine.dispose()
    assert True


def test_fake_scan_is_detected(client, app_bundle) -> None:
    app, _services = app_bundle
    status = client.get("/api/scanner")
    assert status.status_code == 200
    assert status.json()["scanner_found"] is True
    assert client.post("/api/scanner/scan").status_code == 202
    app.state.scanning.wait(5)
    finished = client.get("/api/scanner").json()
    assert finished["phase"] == "idle"
    assert finished["last_scan_ok"] is True
    scan_id = finished["last_scan_id"]
    assert app.state.worker.process_available() == 1
    detail = client.get(f"/api/scans/{scan_id}").json()
    assert detail["region_count"] == 3
    assert detail["dpi"] == 300


def test_second_scan_is_rejected_while_busy(client) -> None:
    class BlockingScanner(FakeScanner):
        def scan(self, request, destination) -> None:  # type: ignore[no-untyped-def]
            time.sleep(0.4)
            super().scan(request, destination)

    client.app.state.scanning.scanner = BlockingScanner()
    assert client.post("/api/scanner/scan").status_code == 202
    rejected = client.post("/api/scanner/scan")
    assert rejected.status_code == 409
    client.app.state.scanning.wait(5)


def test_scanner_error_is_reported(client) -> None:
    class BrokenScanner(FakeScanner):
        def scan(self, request, destination) -> None:  # type: ignore[no-untyped-def]
            raise ScannerError("device busy")

    client.app.state.scanning.scanner = BrokenScanner()
    assert client.post("/api/scanner/scan").status_code == 202
    client.app.state.scanning.wait(5)
    status = client.get("/api/scanner").json()
    assert status["last_scan_ok"] is False
    assert "device busy" in status["last_scan_message"]
    assert client.get("/api/scans", params={"state": "open"}).json() == []


def test_scanner_settings_round_trip(client) -> None:
    saved = client.put(
        "/api/settings",
        json={
            "immich_base_url": "",
            "immich_api_key": "",
            "output_format": "jpeg",
            "jpeg_quality": 90,
            "default_album_id": "",
            "device_name": "genesys:libusb:001:004",
            "resolution_dpi": 600,
            "scan_format": "png",
            "scan_mode": "Gray",
            "width_mm": 216,
            "height_mm": 100,
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["resolution_dpi"] == 600
    assert body["scan_format"] == "png"
    assert body["scan_mode"] == "Gray"
    assert body["width_mm"] == 216
    again = client.get("/api/settings").json()
    assert again["device_name"] == "genesys:libusb:001:004"
    assert again["height_mm"] == 100
