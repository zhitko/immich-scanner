import pytest
from sqlalchemy import select

from app.models import Region, Scan
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed


@pytest.mark.parametrize("action", ["details", "album", "retouch", "unchanged"])
def test_uploaded_photo_returns_to_waiting_after_edit(client, app_bundle, action):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    with services.session_factory() as session:
        regions = list(session.scalars(select(Region).where(Region.scan_id == scan_id)))
        for region in regions:
            region.upload_status = "uploaded"
            region.metadata_synced = True
        region = regions[0]
        region.immich_asset_id = "existing-asset"
        region.description = "Saved description"
        region_id = region.id
        session.get(Scan, scan_id).upload_state = "complete"
        session.commit()
    url = f"/api/scans/{scan_id}/regions/{region_id}"
    if action == "retouch":
        assert client.post(url + "/retouch", json={"dust": True}).status_code == 202
        app.state.worker.process_available()
    else:
        patch = {"description": "Saved description" if action == "unchanged" else "Updated"}
        if action == "album":
            patch = {"album_id": "57dc7f59-250f-4bab-a533-c9fe5e489554"}
        assert client.patch(url, json=patch).status_code == 200
    detail = client.get(f"/api/scans/{scan_id}").json()
    photo = next(r for r in detail["regions"] if r["id"] == region_id)
    assert photo["immich_asset_id"] == "existing-asset"
    if action == "unchanged":
        assert photo["upload_status"] == "uploaded"
        assert detail["upload_state"] == "complete"
    else:
        assert photo["upload_status"] == "pending"
        assert photo["needs_upload"]
        assert detail["upload_state"] == "partial"
