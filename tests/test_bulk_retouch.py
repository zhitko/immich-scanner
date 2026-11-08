from uuid import uuid4

import pytest
from sqlalchemy import select

from app.clock import utcnow
from app.models import Job, Region, Scan
from app.retouch.options import expected_retouch_signature
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed
from tests.test_retouch import MarkRetoucher


@pytest.fixture
def photos(client, app_bundle):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    return client.get(f"/api/scans/{scan_id}").json()["regions"]


def test_bulk_preview_is_read_only_and_skips_any_previous_result(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        first = session.get(Region, photos[0]["id"])
        first.retouch_path = "old-result.png"
        first.retouch_signature = "old-signature"
        first.retouch_status = "stale"
        session.commit()

    preview = client.get("/api/retouch/bulk")
    assert preview.status_code == 200
    assert preview.json() == {
        "total": 3,
        "eligible": 2,
        "retouched": 1,
        "busy": 0,
        "unavailable": 0,
        "queued": 0,
    }
    assert client.get("/api/retouch/bulk?include_retouched=true").json()["eligible"] == 3
    assert not [job for job in client.get("/api/jobs").json() if job["type"] == "retouch"]


def test_bulk_queues_only_eligible_photos_and_does_not_duplicate_jobs(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        first = session.get(Region, photos[0]["id"])
        first.retouch_path = "old-result.png"
        first.retouch_status = "stale"
        first.retouch_faces = True
        session.commit()
    body = {"choice": {"contrast": True, "dust": True, "denoise": False}}
    started = client.post("/api/retouch/bulk", json=body)
    assert started.status_code == 202
    assert started.json()["queued"] == 2
    assert started.json()["retouched"] == 1
    assert client.post("/api/retouch/bulk", json=body).json()["queued"] == 0
    with services.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.type == "retouch")))
        assert len(jobs) == 2
        assert {job.region_id for job in jobs} == {photo["id"] for photo in photos[1:]}
        first = session.get(Region, photos[0]["id"])
        assert first.retouch_faces is True
        assert first.retouch_status == "stale"
        for photo in photos[1:]:
            region = session.get(Region, photo["id"])
            assert region.retouch_contrast and region.retouch_dust
            assert not region.retouch_denoise
            assert not region.retouch_faces
            assert region.retouch_status == "queued"


def test_bulk_includes_previous_results_only_when_requested_and_worker_completes(
    client,
    app_bundle,
    photos,
):
    app, services = app_bundle
    services.retoucher = MarkRetoucher()
    first_id = photos[0]["id"]
    scan_id = client.get(f"/api/photos/{first_id}").json()["id"]
    client.post(
        f"/api/scans/{scan_id}/regions/{first_id}/retouch",
        json={"contrast": True},
    )
    app.state.worker.process_available()
    with services.session_factory() as session:
        old_path = session.get(Region, first_id).retouch_path
    assert services.storage.absolute(old_path).is_file()
    result = client.post(
        "/api/retouch/bulk",
        json={"choice": {"dust": True}, "include_retouched": True},
    )
    assert result.status_code == 202
    assert result.json()["queued"] == 3
    assert app.state.worker.process_available() == 3
    assert not services.storage.absolute(old_path).exists()
    for photo in photos:
        region = client.get(f"/api/photos/{photo['id']}").json()["regions"][0]
        assert region["retouch_ready"] is True
        assert region["retouch_dust"] is True
        assert region["retouch_contrast"] is False
        assert region["upload_source"] == "retouch"
    assert client.get("/api/retouch/bulk").json()["retouched"] == 3
    assert not [job for job in client.get("/api/jobs").json() if job["type"] == "upload"]


def test_bulk_respects_upload_status_and_skips_busy_photos(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        session.get(Region, photos[0]["id"]).upload_status = "uploaded"
        session.get(Region, photos[1]["id"]).upload_status = "uploading"
        session.get(Region, photos[2]["id"]).retouch_status = "running"
        session.commit()
    assert client.get("/api/retouch/bulk?state=uploaded").json()["eligible"] == 1
    waiting = client.get("/api/retouch/bulk?state=open").json()
    assert waiting["total"] == waiting["busy"] == 2
    result = client.post(
        "/api/retouch/bulk",
        json={"choice": {"dust": True}, "state": "uploaded"},
    ).json()
    assert result["queued"] == 1
    assert client.get("/api/retouch/bulk").json()["busy"] == 3


def test_bulk_skips_cleaned_up_scans(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        region = session.get(Region, photos[0]["id"])
        scan = session.get(Scan, region.scan_id)
        scan.files_deleted = True
        session.commit()
    summary = client.get("/api/retouch/bulk").json()
    assert summary["total"] == summary["unavailable"] == 3
    assert summary["eligible"] == 0
    assert client.post("/api/retouch/bulk", json={"choice": {"dust": True}}).json()["queued"] == 0


def test_bulk_rejects_empty_stages_invalid_scope_and_missing_models(client, photos):
    assert client.post("/api/retouch/bulk", json={"choice": {}}).status_code == 422
    assert (
        client.post(
            "/api/retouch/bulk",
            json={"choice": {"dust": True}, "state": "invalid"},
        ).status_code
        == 422
    )
    assert client.get("/api/retouch/bulk?state=invalid").status_code == 422
    missing = client.post("/api/retouch/bulk", json={"choice": {"faces": True}})
    assert missing.status_code == 400
    assert "Missing weights" in missing.json()["detail"]
    assert client.get("/api/retouch/bulk").json()["eligible"] == 3
    assert not [job for job in client.get("/api/jobs").json() if job["type"] == "retouch"]


def test_bulk_rechecks_eligibility_when_starting(client, app_bundle, photos):
    _app, services = app_bundle
    assert client.get("/api/retouch/bulk").json()["eligible"] == 3
    with services.session_factory() as session:
        first = session.get(Region, photos[0]["id"])
        first.retouch_path = "just-finished.png"
        first.retouch_status = "ready"
        first.retouch_signature = expected_retouch_signature(first)
        session.commit()
    result = client.post("/api/retouch/bulk", json={"choice": {"dust": True}}).json()
    assert result["queued"] == 2
    assert result["retouched"] == 1


def test_bulk_handles_more_than_one_query_batch(client, app_bundle, photos):
    _app, services = app_bundle
    now = utcnow()
    with services.session_factory() as session:
        scan_id = session.get(Region, photos[0]["id"]).scan_id
        for position in range(4, 454):
            session.add(
                Region(
                    id=str(uuid4()),
                    scan_id=scan_id,
                    position=position,
                    center_x=50,
                    center_y=50,
                    width=40,
                    height=40,
                    angle_deg=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
    assert client.get("/api/retouch/bulk").json()["eligible"] == 453
    started = client.post("/api/retouch/bulk", json={"choice": {"contrast": True}})
    assert started.status_code == 202
    assert started.json()["queued"] == 453
    counts = client.get("/api/retouch/bulk").json()
    assert counts["eligible"] == 0
    assert counts["busy"] == 453
    with services.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.type == "retouch")))
        assert len(jobs) == len({job.region_id for job in jobs}) == 453
