from app.clock import utcnow
from app.models import Region, Scan
from app.retouch.options import expected_retouch_signature
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed


def test_photo_filters_apply_to_individual_photos(client, app_bundle):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    regions = client.get(f"/api/scans/{scan_id}").json()["regions"]
    original_id, retouched_id, stale_id = [region["id"] for region in regions]
    with services.session_factory() as session:
        original = session.get(Region, original_id)
        original.upload_status = "uploaded"
        original.taken_at = utcnow()
        retouched = session.get(Region, retouched_id)
        retouched.retouch_contrast = True
        retouched.retouch_status = "ready"
        retouched.retouch_path = "retouched.png"
        retouched.retouch_signature = expected_retouch_signature(retouched)
        retouched.taken_at = utcnow()
        stale = session.get(Region, stale_id)
        stale.retouch_status = "stale"
        stale.retouch_path = "old.png"
        session.commit()

    def ids(query=""):
        response = client.get(f"/api/photos{query}")
        assert response.status_code == 200
        return [photo["id"] for photo in response.json()]

    assert ids() == [retouched_id, stale_id]
    assert ids("?state=uploaded") == [original_id]
    assert ids("?state=all") == [original_id, retouched_id, stale_id]
    assert ids("?state=all&filters=original") == [original_id, stale_id]
    assert ids("?state=all&filters=retouched") == [retouched_id]
    assert ids("?state=all&filters=original&filters=retouched") == [
        original_id,
        retouched_id,
        stale_id,
    ]
    assert ids("?state=all&filters=has-date") == [original_id, retouched_id]
    assert ids("?state=all&filters=original&filters=has-date") == [original_id]
    assert ids("?filters=retouched&filters=has-date") == [retouched_id]
    assert ids("?filters=no-date") == [stale_id]
    assert ids("?state=all&filters=no-date") == [stale_id]
    assert ids("?state=uploaded&filters=no-date") == []
    assert ids("?state=all&filters=original&filters=no-date") == [stale_id]
    assert ids("?state=all&filters=retouched&filters=no-date") == []
    assert ids("?state=all&filters=has-date&filters=no-date") == [
        original_id,
        retouched_id,
        stale_id,
    ]
    assert ids("?filters=retouched&filters=has-date&filters=no-date") == [retouched_id]
    assert client.get("/api/photos?state=invalid").status_code == 422
    assert client.get("/api/photos?filters=invalid").status_code == 422
    photo = client.get(f"/api/photos/{retouched_id}").json()
    assert photo["id"] == scan_id
    assert [region["id"] for region in photo["regions"]] == [retouched_id]
    assert client.get("/api/photos/missing").status_code == 404

    with services.session_factory() as session:
        session.get(Scan, scan_id).files_deleted = True
        session.commit()
    assert client.get("/api/photos?state=all").json()[0]["files_deleted"] is True
