from datetime import UTC, datetime
from uuid import uuid4

import cv2
import numpy as np
import pytest
from sqlalchemy import func, select

from app.clock import utcnow
from app.imaging.io import save_rgb
from app.matching import available_fields, visual_features
from app.models import Job, PhotoIndex, PhotoMatch, Region, Scan
from mock_immich.app import FAMILY_ALBUM


def scene(variant=0):
    image = np.full((200, 280, 3), (110, 170, 220), dtype=np.uint8)
    image[110:] = (45, 100, 50)
    cv2.rectangle(image, (35, 60), (115, 155), (150, 65, 30), -1)
    cv2.circle(image, (200 + variant, 95), 25, (230, 190, 150), -1)
    cv2.rectangle(image, (185 + variant, 120), (215 + variant, 180), (180, 40, 50), -1)
    return image


def add_photo(services, image=None, **metadata):
    scan_id, region_id = str(uuid4()), str(uuid4())
    image = scene() if image is None else image
    height, width = image.shape[:2]
    path = f"scans/{scan_id}/original.png"
    save_rgb(image, services.storage.absolute(path), "png")
    with services.session_factory() as session:
        session.add(
            Scan(
                id=scan_id,
                created_at=utcnow(),
                original_filename="photo.png",
                original_path=path,
                width=width,
                height=height,
                dpi=300,
            )
        )
        session.flush()
        region = Region(
            id=region_id,
            scan_id=scan_id,
            position=1,
            center_x=width / 2,
            center_y=height / 2,
            width=width,
            height=height,
            angle_deg=0,
            created_at=utcnow(),
            updated_at=utcnow(),
            **metadata,
        )
        session.add(region)
        session.commit()
    return scan_id, region_id


def run(client, app, score=0.82):
    response = client.post("/api/matching/run", json={"minimum_score": score})
    assert response.status_code == 202
    app.state.worker.process_available()
    status = client.get("/api/matching/status").json()
    assert status["job"]["status"] == "finished", status
    return status


def pairs(client, **params):
    response = client.get("/api/matching/pairs", params=params)
    assert response.status_code == 200
    return response.json()


def copy(client, pair, field, *, replace=False):
    return client.post(
        f"/api/matching/pairs/{pair['source']['id']}/{pair['target']['id']}/copy",
        json={
            "field": field,
            "replace": replace,
            "source_updated_at": pair["source"]["updated_at"],
            "target_updated_at": pair["target"]["updated_at"],
        },
    )


def test_visual_similarity_handles_series_rotations_and_rejects_blank_images():
    source = visual_features(scene())
    other = visual_features(scene(8))
    rotated = visual_features(np.rot90(scene()))
    rng = np.random.default_rng(42)
    unrelated = visual_features(rng.integers(0, 256, size=(200, 280, 3), dtype=np.uint8))
    assert float((source @ other[0]).max()) > 0.9
    assert float((source @ rotated[0]).max()) > 0.99
    assert float((source @ unrelated[0]).max()) < 0.82
    assert np.isfinite(source).all()
    with pytest.raises(ValueError, match="visual detail"):
        visual_features(np.full((200, 280, 3), 120, dtype=np.uint8))


def test_background_run_indexes_all_photos_reuses_index_and_finds_directed_pairs(
    client, app_bundle
):
    app, services = app_bundle
    _, source = add_photo(
        services,
        taken_at=datetime(1980, 5, 1, tzinfo=UTC),
        description="Family picnic",
        upload_status="uploaded",
    )
    _, target = add_photo(services, scene(8))
    add_photo(services, np.random.default_rng(42).integers(0, 256, (200, 280, 3), dtype=np.uint8))
    assert client.get("/api/matching/status").json() == {"job": None, "progress": None}
    assert pairs(client) == {"items": [], "total": 0}
    queued = client.post("/api/matching/run", json={})
    assert queued.status_code == 202
    assert client.post("/api/matching/run", json={}).json() == queued.json()
    assert client.get("/api/matching/status").json()["job"]["status"] == "queued"
    app.state.worker.process_available()
    result = pairs(client)
    assert result["total"] == 1
    pair = result["items"][0]
    assert pair["source"]["id"] == source
    assert pair["target"]["id"] == target
    assert pair["fields"] == ["taken_at", "description"]
    assert 0.9 < pair["score"] <= 1
    with services.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhotoIndex)) == 3
    status = run(client, app)
    assert status["progress"]["reused"] == 3
    assert status["progress"]["indexed"] == 3
    assert status["progress"]["pairs"] == 1


def test_copy_individual_fields_preserves_existing_metadata_and_marks_for_sync(client, app_bundle):
    app, services = app_bundle
    add_photo(
        services,
        taken_at=datetime(1982, 7, 3, 10, 30, tzinfo=UTC),
        description="Picnic",
        album_id=FAMILY_ALBUM,
        latitude=0,
        longitude=0,
        is_favorite=True,
        rating=4,
        visibility="archive",
    )
    scan, target = add_photo(
        services,
        description="Existing caption",
        upload_status="uploaded",
        metadata_synced=True,
        album_linked=True,
    )
    run(client, app)
    for field in ["taken_at", "album_id", "location", "is_favorite", "rating", "visibility"]:
        pair = next(p for p in pairs(client)["items"] if p["target"]["id"] == target)
        assert "description" not in pair["fields"]
        result = copy(client, pair, field)
        assert result.status_code == 200, result.text
        photo = result.json()
        assert photo["description"] == "Existing caption"
        assert photo["needs_upload"] is True
        assert photo["upload_status"] == "uploaded"
        assert copy(client, pair, field).status_code == 409
    photo = client.get(f"/api/photos/{target}").json()["regions"][0]
    assert photo["taken_at"] == "1982-07-03T10:30:00Z"
    assert photo["album_id"] == FAMILY_ALBUM
    assert photo["latitude"] == photo["longitude"] == 0
    assert photo["is_favorite"] is True
    assert photo["rating"] == 4
    assert photo["visibility"] == "archive"
    assert photo["metadata_synced"] is False
    assert photo["album_linked"] is False
    assert photo["center_x"] == 140
    assert not any(p["target"]["id"] == target for p in pairs(client)["items"])
    assert client.get(f"/api/scans/{scan}/regions/{target}/preview").status_code == 200


@pytest.mark.parametrize(
    "field,source_values,target_values",
    [
        ("description", {"description": "Picnic"}, {"description": "Old caption"}),
        (
            "taken_at",
            {"taken_at": datetime(1980, 5, 1, tzinfo=UTC)},
            {"taken_at": datetime(1990, 6, 2, tzinfo=UTC)},
        ),
        ("album_id", {"album_id": FAMILY_ALBUM}, {"album_id": "previous-album"}),
        ("location", {"latitude": 0, "longitude": 0}, {"latitude": 42, "longitude": 12}),
        ("location", {"latitude": 0, "longitude": 0}, {"latitude": 42, "longitude": None}),
        ("rating", {"rating": 4}, {"rating": 2}),
        ("visibility", {"visibility": "archive"}, {"visibility": "timeline"}),
        ("is_favorite", {"is_favorite": True}, {"is_favorite": True}),
    ],
)
def test_explicit_replace_updates_only_selected_field(
    client, app_bundle, field, source_values, target_values
):
    app, services = app_bundle
    # A missing field keeps this pair eligible for matching.
    source_metadata = {"description": "Source caption", "rating": 5, **source_values}
    add_photo(services, **source_metadata)
    _, target_id = add_photo(
        services, **target_values, upload_status="uploaded", metadata_synced=True, album_linked=True
    )
    run(client, app)
    pair = next(p for p in pairs(client)["items"] if p["target"]["id"] == target_id)
    assert field not in pair["fields"]
    assert copy(client, pair, field).status_code == 409
    response = copy(client, pair, field, replace=True)
    assert response.status_code == 200, response.text
    result = response.json()
    replaced_keys = {"latitude", "longitude"} if field == "location" else {field}
    for key in replaced_keys:
        assert result[key] == pair["source"][key]
    for key in [
        "description",
        "taken_at",
        "album_id",
        "latitude",
        "longitude",
        "is_favorite",
        "rating",
        "visibility",
    ]:
        if key not in replaced_keys:
            assert result[key] == pair["target"][key]
    if field == "album_id":
        assert result["album_linked"] is False
    else:
        assert result["metadata_synced"] is False
    assert result["needs_upload"] is True
    assert copy(client, pair, field, replace=True).status_code == 409


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("changed", ["source", "target"])
def test_copy_rejects_metadata_changed_after_review(client, app_bundle, changed, replace):
    app, services = app_bundle
    add_photo(services, description="Original source caption")
    add_photo(services)
    run(client, app)
    pair = pairs(client)["items"][0]
    photo = pair[changed]
    client.patch(
        f"/api/scans/{photo['scan_id']}/regions/{photo['id']}",
        json={"description": "New caption from another editor"},
    )
    assert copy(client, pair, "description", replace=replace).status_code == 409
    target = client.get(f"/api/photos/{pair['target']['id']}").json()["regions"][0]
    assert target["description"] == (
        "New caption from another editor" if changed == "target" else ""
    )


def test_copy_rejects_changed_crop_and_run_reindexes_only_that_photo(client, app_bundle):
    app, services = app_bundle
    add_photo(services, description="Picnic")
    scan_id, target_id = add_photo(services)
    run(client, app)
    pair = pairs(client)["items"][0]
    client.post(f"/api/scans/{scan_id}/regions/{target_id}/rotate")
    assert pairs(client)["total"] == 0
    assert copy(client, pair, "description").status_code == 409
    status = run(client, app)
    assert status["progress"]["reused"] == 1
    assert pairs(client)["total"] == 1
    assert copy(client, pairs(client)["items"][0], "description").status_code == 200
    assert pairs(client)["total"] == 0


def test_dismissal_survives_reruns_and_deleting_photo_cascades_index(client, app_bundle):
    app, services = app_bundle
    source_scan, source = add_photo(services, description="Picnic")
    _, target = add_photo(services)
    run(client, app)
    pair = pairs(client)["items"][0]
    response = client.post(f"/api/matching/pairs/{source}/{target}/dismiss")
    assert response.status_code == 204
    assert copy(client, pair, "description").status_code == 409
    assert pairs(client)["total"] == 0
    run(client, app)
    assert pairs(client)["total"] == 0
    client.delete(f"/api/scans/{source_scan}")
    with services.session_factory() as session:
        assert session.get(PhotoIndex, source) is None
        assert session.get(PhotoMatch, (source, target)) is None
        assert session.get(PhotoIndex, target) is not None


def test_removed_corrupt_and_blank_files_are_reported_and_do_not_block_matches(client, app_bundle):
    app, services = app_bundle
    source_scan, _ = add_photo(services, description="Picnic")
    add_photo(services)
    removed_scan, _ = add_photo(services)
    client.delete(f"/api/scans/{removed_scan}/files")
    corrupt_scan, _ = add_photo(services)
    services.storage.absolute(f"scans/{corrupt_scan}/original.png").write_bytes(b"not an image")
    add_photo(services, np.full((200, 280, 3), 100, dtype=np.uint8))
    status = run(client, app)
    assert status["progress"]["indexed"] == 2
    assert status["progress"]["skipped"] == 3
    assert len(status["progress"]["warnings"]) == 3
    pair = pairs(client)["items"][0]
    client.delete(f"/api/scans/{source_scan}/files")
    assert pairs(client)["total"] == 0
    assert copy(client, pair, "description").status_code == 409


def test_pagination_validation_and_best_three_sources_per_target(client, app_bundle):
    app, services = app_bundle
    for index in range(5):
        add_photo(services, scene(index), description="Caption")
    _, target = add_photo(services)
    run(client, app)
    result = pairs(client, limit=2)
    assert result["total"] == 3
    assert len(result["items"]) == 2
    assert all(p["target"]["id"] == target for p in result["items"])
    assert len(pairs(client, offset=2, limit=2)["items"]) == 1
    assert pairs(client, offset=3)["items"] == []
    assert result["items"][0]["score"] >= result["items"][1]["score"]
    assert client.get("/api/matching/pairs?offset=-1").status_code == 422
    assert client.post("/api/matching/run", json={"minimum_score": 1.1}).status_code == 422
    assert client.post("/api/matching/run", json={"minimum_score": 0.1}).status_code == 422
    pair = result["items"][0]
    assert copy(client, pair, "upload_status").status_code == 422
    assert copy(client, pair, "taken_at").status_code == 409
    assert copy(client, pair, "taken_at", replace=True).status_code == 409
    assert client.post("/api/matching/pairs/missing/missing/dismiss").status_code == 404
    pair["source"]["id"] = "missing"
    assert copy(client, pair, "description").status_code == 404


def test_empty_collection_and_photos_without_metadata(client, app_bundle):
    app, services = app_bundle
    assert run(client, app)["progress"]["indexed"] == 0
    add_photo(services)
    add_photo(services)
    assert run(client, app)["progress"]["indexed"] == 2
    assert pairs(client)["total"] == 0
    # A newly added caption should create suggestions without reindexing pixels.
    with services.session_factory() as session:
        source = session.scalar(select(Region).limit(1))
        source.description = "New caption"
        session.commit()
    assert run(client, app)["progress"]["reused"] == 2
    assert pairs(client)["total"] == 1


def test_partial_location_is_never_overwritten():
    source = Region(latitude=0, longitude=0, description="  ", is_favorite=False)
    target = Region(latitude=42, longitude=None)
    assert available_fields(source, target) == []


def test_photo_deleted_while_indexing_does_not_fail_run(client, app_bundle, monkeypatch):
    app, services = app_bundle
    scan_id, photo_id = add_photo(services, description="Picnic")

    def delete_during_decode(image):
        assert client.delete(f"/api/scans/{scan_id}").status_code == 204
        return visual_features(image)

    monkeypatch.setattr("app.matching.visual_features", delete_during_decode)
    run(client, app)
    assert pairs(client)["total"] == 0
    with services.session_factory() as session:
        assert session.get(PhotoIndex, photo_id) is None


@pytest.mark.parametrize("action", ["delete", "dismiss", "rotate", "metadata"])
def test_results_recheck_changes_during_scoring(client, app_bundle, monkeypatch, action):
    app, services = app_bundle
    add_photo(services, description="Picnic")
    scan_id, target_id = add_photo(services)
    run(client, app)
    pair = pairs(client)["items"][0]
    changed = False

    def change_during_scoring(source, target):
        nonlocal changed
        if not changed:
            changed = True
            if action == "delete":
                response = client.delete(f"/api/scans/{scan_id}")
            elif action == "dismiss":
                response = client.post(
                    f"/api/matching/pairs/{pair['source']['id']}/{target_id}/dismiss"
                )
            elif action == "rotate":
                response = client.post(f"/api/scans/{scan_id}/regions/{target_id}/rotate")
            else:
                response = client.patch(
                    f"/api/scans/{scan_id}/regions/{target_id}",
                    json={"description": "Already filled"},
                )
            assert response.is_success
        return available_fields(source, target)

    monkeypatch.setattr("app.matching.available_fields", change_during_scoring)
    run(client, app)
    assert changed
    assert pairs(client)["total"] == 0
    with services.session_factory() as session:
        match = session.get(PhotoMatch, (pair["source"]["id"], target_id))
        if action == "dismiss":
            assert match.dismissed
        else:
            assert match is None


def test_failed_matching_can_be_retried_without_losing_previous_pairs(
    client, app_bundle, monkeypatch
):
    app, services = app_bundle
    add_photo(services, description="Picnic")
    add_photo(services)
    run(client, app)
    previous = pairs(client)

    def fail(*_args):
        raise RuntimeError("Test failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.jobs.worker.HANDLERS", {"match": fail})
        response = client.post("/api/matching/run", json={})
        app.state.worker.process_available()
        job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
        assert job["status"] == "failed"
    assert pairs(client) == previous
    run(client, app)
    assert pairs(client)["total"] == 1
    with services.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.type == "match")) == 3
