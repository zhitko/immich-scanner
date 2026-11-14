import pytest

from app.models import Region, Scan
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed

PROCESSING_FLAGS = (
    "retouch_upscale",
    "retouch_denoise",
    "retouch_faces",
    "retouch_colorize",
    "retouch_scratches",
    "retouch_color_balance",
    "retouch_contrast",
    "retouch_dust",
    "retouch_deblur",
    "retouch_gentle_denoise",
    "retouch_paper_mesh",
    "retouch_paper_embossed",
    "retouch_light_corners",
)


@pytest.mark.parametrize(
    "enabled, output_scale",
    [(flag, 4) for flag in PROCESSING_FLAGS] + [(None, 4), ("retouch_upscale", 2)],
)
def test_processing_defaults_apply_to_new_photos_and_preserve_existing_choices(
    client, app_bundle, enabled, output_scale
):
    expected = {flag: flag == enabled for flag in PROCESSING_FLAGS}
    expected["retouch_output_scale"] = output_scale
    saved = client.put("/api/settings", json=expected)
    assert saved.status_code == 200
    for response in (saved, client.get("/api/settings")):
        assert {key: response.json()[key] for key in expected} == expected

    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    scan_url = f"/api/scans/{scan_id}"
    detected = client.get(scan_url).json()["regions"]
    assert detected
    added = client.post(
        f"{scan_url}/regions",
        json={"center_x": 800, "center_y": 200, "width": 80, "height": 60},
    )
    assert added.status_code == 201
    for photo in [*detected, added.json()]:
        assert {key: photo[key] for key in expected} == expected
        opened = client.get(f"/api/photos/{photo['id']}")
        assert opened.status_code == 200
        assert {key: opened.json()["regions"][0][key] for key in expected} == expected

    # Settings are defaults for new photos, not overrides for existing photos.
    changed = {flag: not expected[flag] for flag in PROCESSING_FLAGS}
    changed["retouch_output_scale"] = 2 if output_scale == 4 else 4
    assert client.put("/api/settings", json=changed).status_code == 200
    for photo in client.get(scan_url).json()["regions"]:
        assert {key: photo[key] for key in expected} == expected
        opened = client.get(f"/api/photos/{photo['id']}").json()["regions"][0]
        assert {key: opened[key] for key in expected} == expected

    # A per-photo edit must also survive reopening both editor views.
    photo_id = detected[0]["id"]
    patched = client.patch(f"{scan_url}/regions/{photo_id}", json=changed)
    assert patched.status_code == 200
    reopened = client.get(f"/api/photos/{photo_id}").json()["regions"][0]
    assert {key: reopened[key] for key in changed} == changed
    reopened_scan = client.get(scan_url).json()["regions"]
    reopened = next(photo for photo in reopened_scan if photo["id"] == photo_id)
    assert {key: reopened[key] for key in changed} == changed

    added = client.post(
        f"{scan_url}/regions",
        json={"center_x": 800, "center_y": 300, "width": 80, "height": 60},
    )
    assert added.status_code == 201
    assert {key: added.json()[key] for key in changed} == changed

    next_scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    next_photos = client.get(f"/api/scans/{next_scan_id}").json()["regions"]
    assert next_photos
    for photo in next_photos:
        assert {key: photo[key] for key in changed} == changed

    # Explicit editor entry refreshes every processing field for untouched photos.
    for url in (f"/api/photos/{photo_id}", scan_url):
        assert client.put("/api/settings", json=expected).status_code == 200
        opened = client.get(url, params={"apply_defaults": True})
        assert opened.status_code == 200
        for photo in opened.json()["regions"]:
            assert {key: photo[key] for key in expected} == expected
        # The defaults are saved, rather than merely displayed in the response.
        reopened = client.get(f"/api/photos/{photo_id}").json()["regions"][0]
        assert {key: reopened[key] for key in expected} == expected
        assert client.patch(f"{scan_url}/regions/{photo_id}", json=changed).status_code == 200


@pytest.mark.parametrize("view", ["photos", "scans"])
def test_open_defaults_apply_default_album_to_unuploaded_photos(client, app_bundle, view):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    photo_id = client.get(f"/api/scans/{scan_id}").json()["regions"][0]["id"]

    settings = client.get("/api/settings").json()
    settings["default_album_id"] = "11111111-1111-4111-8111-111111111111"
    saved = client.put("/api/settings", json=settings)
    assert saved.status_code == 200
    assert saved.json()["default_album_id"] == settings["default_album_id"]
    assert client.get("/api/settings").json()["default_album_id"] == settings["default_album_id"]

    target_id = photo_id if view == "photos" else scan_id
    opened = client.get(f"/api/{view}/{target_id}", params={"apply_defaults": True})
    assert opened.status_code == 200
    region = next(item for item in opened.json()["regions"] if item["id"] == photo_id)
    assert region["album_id"] == settings["default_album_id"]

    reopened = client.get(f"/api/photos/{photo_id}").json()["regions"][0]
    assert reopened["album_id"] == settings["default_album_id"]


@pytest.mark.parametrize("view", ["photos", "scans"])
@pytest.mark.parametrize(
    "asset_id, visibility, expected",
    [(None, None, "archive"), (None, "hidden", "hidden"), ("uploaded", None, None)],
)
def test_open_visibility_default(client, app_bundle, view, asset_id, visibility, expected):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    photo_id = client.get(f"/api/scans/{scan_id}").json()["regions"][0]["id"]
    with services.session_factory() as session:
        region = session.get(Region, photo_id)
        region.immich_asset_id = asset_id
        region.visibility = visibility
        session.commit()
    assert client.put("/api/settings", json={"default_visibility": "archive"}).status_code == 200
    target_id = photo_id if view == "photos" else scan_id
    opened = client.get(f"/api/{view}/{target_id}?apply_defaults=true")
    assert opened.status_code == 200
    photo = next(item for item in opened.json()["regions"] if item["id"] == photo_id)
    assert photo["visibility"] == expected
    assert client.get(f"/api/photos/{photo_id}").json()["regions"][0]["visibility"] == expected


@pytest.mark.parametrize("view", ["photos", "scans"])
@pytest.mark.parametrize(
    "status, path, signature, refresh",
    [
        ("none", None, None, True),
        ("failed", None, None, True),
        ("queued", None, None, False),
        ("running", None, None, False),
        ("ready", "retouched.png", "old-signature", False),
        ("stale", "retouched.png", "old-signature", False),
        ("failed", "retouched.png", "old-signature", False),
        ("none", "retouched.png", None, False),
        ("none", None, "old-signature", False),
    ],
)
def test_open_defaults_preserve_retouch_history_and_active_jobs(
    client, app_bundle, view, status, path, signature, refresh
):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    photo_id = client.get(f"/api/scans/{scan_id}").json()["regions"][0]["id"]
    with services.session_factory() as session:
        region = session.get(Region, photo_id)
        region.retouch_status = status
        region.retouch_path = path
        region.retouch_signature = signature
        region.retouch_error = "Previous error" if status == "failed" else None
        previous_updated_at = region.updated_at
        session.commit()
    assert (
        client.put(
            "/api/settings", json={"retouch_denoise": True, "retouch_output_scale": 2}
        ).status_code
        == 200
    )
    target_id = photo_id if view == "photos" else scan_id
    opened = client.get(f"/api/{view}/{target_id}?apply_defaults=true")
    assert opened.status_code == 200
    photo = next(item for item in opened.json()["regions"] if item["id"] == photo_id)
    assert photo["retouch_denoise"] is refresh
    assert photo["retouch_output_scale"] == (2 if refresh else 4)
    assert photo["retouch_status"] == status
    assert photo["retouch_signature"] == signature
    with services.session_factory() as session:
        region = session.get(Region, photo_id)
        assert region.retouch_path == path
        assert region.updated_at == previous_updated_at
        assert region.retouch_error == ("Previous error" if status == "failed" else None)


@pytest.mark.parametrize("view", ["photos", "scans"])
def test_open_defaults_skip_deleted_files(client, app_bundle, view):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    photo_id = client.get(f"/api/scans/{scan_id}").json()["regions"][0]["id"]
    with services.session_factory() as session:
        session.get(Scan, scan_id).files_deleted = True
        session.commit()
    assert client.put("/api/settings", json={"retouch_denoise": True}).status_code == 200
    target_id = photo_id if view == "photos" else scan_id
    opened = client.get(f"/api/{view}/{target_id}?apply_defaults=true")
    assert opened.status_code == 200
    assert all(not photo["retouch_denoise"] for photo in opened.json()["regions"])
