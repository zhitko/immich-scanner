import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.scanner.base import ScanRequest
from app.scanner.fake import FakeScanner
from app.schemas import ClientSettings
from app.service import AgentService
from app.state_store import StateStore
from app.uploader import ScanUploader


def _app(tmp_path: Path, transport: httpx.BaseTransport) -> TestClient:
    store = StateStore(
        tmp_path,
        ClientSettings(server_url="http://archive.test", api_token="secret", image_format="png"),
    )
    http = httpx.Client(transport=transport)
    service = AgentService(store, FakeScanner(), ScanUploader(http), tmp_path)
    settings = Settings(data_dir=tmp_path, scanner_backend="fake")
    return TestClient(create_app(settings, service))


def test_scan_uploads_the_fake_bed(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["token"] = request.headers.get("x-scanner-token", "")
        seen["body"] = request.content.decode("latin1")
        return httpx.Response(201, json={"scan_id": "scan-1", "job_id": "job-1"})

    client = _app(tmp_path, httpx.MockTransport(handler))
    health = client.get("/api/status")
    assert health.status_code == 200
    assert health.json()["scanner_found"] is True
    assert health.json()["server_reachable"] is True

    started = client.post("/api/scan")
    assert started.status_code == 202
    client.app.state.service.wait(5)
    status = client.get("/api/status").json()
    assert status["phase"] == "idle"
    assert status["last_scan_ok"] is True
    assert status["last_scan_id"] == "scan-1"
    assert seen["token"] == "secret"
    assert 'name="file"' in seen["body"]
    assert "dpi" in seen["body"]


def test_settings_persist_through_the_api(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = _app(tmp_path, httpx.MockTransport(handler))
    saved = client.put(
        "/api/settings",
        json={
            "server_url": "http://other.local:8080",
            "api_token": "next",
            "device_name": "fake:0",
            "resolution_dpi": 600,
            "image_format": "tiff",
            "mode": "Color",
            "width_mm": None,
            "height_mm": None,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["resolution_dpi"] == 600
    assert client.get("/api/settings").json()["api_token"] == "next"


def test_second_scan_is_rejected_while_busy(tmp_path: Path) -> None:
    class BlockingScanner(FakeScanner):
        def scan(self, request: ScanRequest, destination: Path) -> None:
            time.sleep(0.4)
            super().scan(request, destination)

    store = StateStore(
        tmp_path,
        ClientSettings(server_url="http://archive.test", api_token="secret"),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"scan_id": "scan-2"})

    service = AgentService(
        store,
        BlockingScanner(),
        ScanUploader(httpx.Client(transport=httpx.MockTransport(handler))),
        tmp_path,
    )
    client = TestClient(create_app(Settings(data_dir=tmp_path, scanner_backend="fake"), service))
    assert client.post("/api/scan").status_code == 202
    rejected = client.post("/api/scan")
    assert rejected.status_code == 409
    service.wait(5)
