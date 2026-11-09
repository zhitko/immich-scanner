import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.clock import utcnow
from app.models import Job, Region, Scan
from app.retouch.options import expected_retouch_signature
from tests.synthetic import encode_png, make_bed
from tests.test_api import RecordingImmich, _import_bed


@pytest.fixture
def photos(client, app_bundle):
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    return client.get(f"/api/scans/{scan_id}").json()["regions"]


def test_preview_is_read_only_and_skips_uploaded(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        session.get(Region, photos[0]["id"]).upload_status = "uploaded"
        session.get(Region, photos[1]["id"]).upload_status = "failed"
        session.commit()
    assert client.get("/api/uploads/bulk").json() == {
        "total": 3, "eligible": 2, "uploaded": 1, "busy": 0,
        "unavailable": 0, "retouch_not_ready": 0, "queued": 0,
    }
    assert client.get("/api/uploads/bulk?include_uploaded=true").json()["eligible"] == 3
    assert not [job for job in client.get("/api/jobs").json() if job["type"] == "upload"]


def test_queues_selected_photos_once_per_scan_and_worker_completes(client, app_bundle, photos):
    app, services = app_bundle
    gateway = RecordingImmich()
    services.build_gateway = lambda _url, _key: gateway
    settings = client.get("/api/settings").json()
    settings.update(immich_base_url="http://immich:2283", immich_api_key="test-key")
    client.put("/api/settings", json=settings)
    with services.session_factory() as session:
        session.get(Region, photos[0]["id"]).upload_status = "uploaded"
        session.commit()
    result = client.post("/api/uploads/bulk", json={})
    assert result.status_code == 202
    assert result.json()["queued"] == 2
    assert client.post("/api/uploads/bulk", json={}).json()["queued"] == 0
    with services.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.type == "upload")))
        assert len(jobs) == 1
        assert set(json.loads(jobs[0].payload)["region_ids"]) == {
            photo["id"] for photo in photos[1:]
        }
    assert app.state.worker.process_available() == 1
    assert len(gateway.uploads) == 2
    assert client.get("/api/uploads/bulk").json()["uploaded"] == 3
    assert client.post(
        "/api/uploads/bulk", json={"include_uploaded": True}
    ).json()["queued"] == 3


def test_skips_busy_and_stale_retouch_without_changing_version(client, app_bundle, photos):
    _app, services = app_bundle
    with services.session_factory() as session:
        first, second, third = [session.get(Region, photo["id"]) for photo in photos]
        first.retouch_status = "running"
        second.upload_source = "retouch"
        second.retouch_status = "stale"
        third.upload_source = "retouch"
        third.retouch_status = "ready"
        third.retouch_path = "result.png"
        third.retouch_signature = expected_retouch_signature(third)
        session.commit()
    summary = client.get("/api/uploads/bulk").json()
    assert summary["eligible"] == summary["busy"] == summary["retouch_not_ready"] == 1
    result = client.post("/api/uploads/bulk", json={}).json()
    assert result["queued"] == 1
    with services.session_factory() as session:
        assert session.get(Region, photos[1]["id"]).upload_source == "retouch"
        job = session.scalar(select(Job).where(Job.type == "upload"))
        assert json.loads(job.payload)["region_ids"] == [photos[2]["id"]]


def test_skips_deleted_files_and_rechecks_before_start(client, app_bundle, photos):
    _app, services = app_bundle
    assert client.get("/api/uploads/bulk").json()["eligible"] == 3
    with services.session_factory() as session:
        region = session.get(Region, photos[0]["id"])
        session.get(Scan, region.scan_id).files_deleted = True
        session.commit()
    summary = client.post("/api/uploads/bulk", json={}).json()
    assert summary["unavailable"] == 3
    assert summary["queued"] == 0
    assert client.post("/api/uploads/bulk", json={"unexpected": True}).status_code == 422


def test_large_batch_across_scans_and_existing_scan_upload(client, app_bundle, photos):
    app, services = app_bundle
    other_id = _import_bed(services, encode_png(make_bed()), filename="other.png")
    app.state.worker.process_available()
    with services.session_factory() as session:
        scan_id = session.get(Region, photos[0]["id"]).scan_id
        now = utcnow()
        for position in range(4, 454):
            session.add(Region(
                id=str(uuid4()), scan_id=scan_id, position=position,
                center_x=50, center_y=50, width=40, height=40, angle_deg=0,
                created_at=now, updated_at=now,
            ))
        session.commit()
    client.post(f"/api/scans/{other_id}/upload", json={})
    summary = client.post("/api/uploads/bulk", json={}).json()
    assert summary["queued"] == 453
    assert summary["busy"] == 3
    assert client.post("/api/uploads/bulk", json={}).json()["queued"] == 0
    with services.session_factory() as session:
        jobs = list(session.scalars(select(Job).where(Job.type == "upload")))
        assert len(jobs) == 2
