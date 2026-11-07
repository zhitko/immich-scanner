import os
import time

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.synthetic import encode_png, make_bed
from tests.test_api import RecordingImmich, _import_bed


def _preview(client, scan_id: str, region_id: str):
    response = client.get(f"/api/scans/{scan_id}/regions/{region_id}/preview")
    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8")
    return response.content


def test_quarter_turns_do_not_rewrite_the_preview(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    url = f"/api/scans/{scan_id}/regions/{region['id']}/rotate"
    original = _preview(client, scan_id, region["id"])

    assert client.post(url).json()["quarter_turns"] == 1
    assert _preview(client, scan_id, region["id"]) == original
    assert client.post(url).json()["quarter_turns"] == 2
    assert _preview(client, scan_id, region["id"]) == original


def test_upload_still_applies_quarter_turns(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed(speck=False)))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert client.post(f"/api/scans/{scan_id}/regions/{region['id']}/rotate").status_code == 200
    preview = _jpeg_size(_preview(client, scan_id, region["id"]))
    assert preview[0] != preview[1]

    gateway = RecordingImmich()
    services.build_gateway = lambda _url, _key: gateway
    saved = client.put(
        "/api/settings",
        json={"immich_base_url": "http://immich.local:2283", "immich_api_key": "secret-key"},
    )
    assert saved.status_code == 200
    queued = client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [region["id"]]})
    assert queued.status_code == 202
    assert app.state.worker.process_available() == 1
    uploaded = _jpeg_size(gateway.uploads[0].content)
    assert uploaded == (preview[1], preview[0])


def test_a_fresh_preview_is_kept_when_the_crop_changes(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    folder = services.storage.root / "scans" / scan_id / "previews"

    _preview(client, scan_id, region["id"])
    _shift(client, scan_id, region, 1)
    _preview(client, scan_id, region["id"])
    fresh = sorted(path.name for path in folder.glob("*.jpg"))
    assert len(fresh) == 2

    stale = folder / fresh[0]
    os.utime(stale, (time.time() - 120, time.time() - 120))
    _shift(client, scan_id, region, 2)
    _preview(client, scan_id, region["id"])
    names = {path.name for path in folder.glob("*.jpg")}
    assert stale.name not in names
    assert fresh[1] in names
    assert len(names) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"center_x": 720, "center_y": 620},
        {"width": 180, "height": 120},
        {"angle_deg": 25},
    ],
    ids=["move", "resize", "rotate-borders"],
)
def test_preview_matches_borders_as_soon_as_save_response_starts(
    client, app_bundle, change
) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    original = _preview(client, scan_id, region["id"])
    geometry = {
        key: region[key] for key in ("center_x", "center_y", "width", "height", "angle_deg")
    } | change
    region_url = f"/api/scans/{scan_id}/regions/{region['id']}"
    version = ":".join(str(value) for value in geometry.values())
    previews = []

    async def save_with_immediate_preview(scope, receive, send):
        async def on_send(message):
            if message["type"] == "http.response.start" and message["status"] == 200:
                # Fetch before dependency cleanup, just as a browser can when it
                # receives the save response. TestClient normally waits for cleanup.
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as browser:
                    previews.append(
                        await browser.get(f"{region_url}/preview", params={"v": version})
                    )
            await send(message)

        await app(scope, receive, on_send)

    response = TestClient(save_with_immediate_preview).patch(region_url, json=geometry)
    assert response.status_code == 200
    assert len(previews) == 1
    assert previews[0].status_code == 200
    current = _preview(client, scan_id, region["id"])
    assert current != original
    assert previews[0].content == current
    assert _jpeg_size(current) == (round(geometry["width"]), round(geometry["height"]))


def _jpeg_size(content: bytes) -> tuple[int, int]:
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    return width, height


def _shift(client, scan_id: str, region: dict, degrees: float) -> None:
    response = client.patch(
        f"/api/scans/{scan_id}/regions/{region['id']}",
        json={
            "center_x": region["center_x"],
            "center_y": region["center_y"],
            "width": region["width"],
            "height": region["height"],
            "angle_deg": region["angle_deg"] + degrees,
        },
    )
    assert response.status_code == 200
