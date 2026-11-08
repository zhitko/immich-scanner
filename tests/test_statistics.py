from datetime import UTC, datetime

from app.models import Region, Scan


def test_statistics_empty_collection(client) -> None:
    response = client.get("/api/statistics")
    assert response.status_code == 200
    for key, value in response.json().items():
        assert value == (None if key.endswith("_at") else 0), key


def test_statistics_counts_photos_without_multiplying_scans(client, app_bundle) -> None:
    _, services = app_bundle
    first = datetime(2025, 1, 1, tzinfo=UTC)
    latest = datetime(2026, 11, 1, tzinfo=UTC)
    taken = datetime(1999, 6, 12, tzinfo=UTC)
    with services.session_factory() as session:
        session.add_all(
            [
                Scan(
                    id="cleaned",
                    created_at=first,
                    original_filename="first.png",
                    width=100,
                    height=100,
                    upload_state="complete",
                    files_deleted=True,
                ),
                Scan(
                    id="open",
                    created_at=latest,
                    original_filename="latest.png",
                    width=100,
                    height=100,
                    upload_state="partial",
                    detection_error="Failed",
                ),
                Scan(
                    id="empty",
                    created_at=latest,
                    original_filename="empty.png",
                    width=100,
                    height=100,
                ),
            ]
        )
        session.flush()
        for index, status in enumerate(["uploaded", "uploaded", "pending", "failed", "uploading"]):
            session.add(
                Region(
                    id=f"photo-{index}",
                    scan_id="cleaned" if index < 2 else "open",
                    position=index,
                    center_x=50,
                    center_y=50,
                    width=20,
                    height=20,
                    angle_deg=0,
                    created_at=first,
                    updated_at=latest,
                    upload_status=status,
                    taken_at=taken if index == 0 else None,
                    description="Family" if index == 0 else " \t\n\r ",
                    album_id="family" if index < 2 else None,
                    latitude=0 if index == 0 else None,
                    longitude=0 if index == 0 else None,
                    is_favorite=index == 0,
                    rating=5 if index == 0 else None,
                    metadata_synced=index in (0, 2),
                    uploaded_at=latest if index < 2 else None,
                )
            )
        session.commit()

    response = client.get("/api/statistics")
    assert response.status_code == 200
    assert response.json() == {
        "scans": 3,
        "scans_uploaded": 1,
        "scans_cleaned_up": 1,
        "detection_errors": 1,
        "photos": 5,
        "uploaded": 2,
        "pending": 1,
        "uploading": 1,
        "failed": 1,
        "with_date": 1,
        "with_description": 1,
        "with_album": 2,
        "with_location": 1,
        "favorites": 1,
        "with_rating": 1,
        "metadata_synced": 1,
        "albums": 1,
        "retouched": 0,
        "retouched_upscale": 0,
        "retouched_denoise": 0,
        "retouched_faces": 0,
        "retouched_colorize": 0,
        "retouched_scratches": 0,
        "retouched_color_balance": 0,
        "retouched_contrast": 0,
        "retouched_dust": 0,
        "retouched_deblur": 0,
        "retouched_gentle_denoise": 0,
        "first_scan_at": "2025-01-01T00:00:00Z",
        "latest_scan_at": "2026-11-01T00:00:00Z",
        "earliest_photo_at": "1999-06-12T00:00:00Z",
        "latest_photo_at": "1999-06-12T00:00:00Z",
        "latest_upload_at": "2026-11-01T00:00:00Z",
    }

    assert client.delete("/api/scans/cleaned").status_code == 204
    remaining = client.get("/api/statistics").json()
    assert remaining["scans"] == 2
    assert remaining["photos"] == 3
    assert remaining["uploaded"] == 0


def test_statistics_not_limited_to_scan_list_page(client, app_bundle) -> None:
    _, services = app_bundle
    with services.session_factory() as session:
        session.add_all(
            [
                Scan(
                    id=f"scan-{index}",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    original_filename="scan.png",
                    width=100,
                    height=100,
                )
                for index in range(501)
            ]
        )
        session.commit()
    assert client.get("/api/statistics").json()["scans"] == 501


def test_statistics_retouch_counts_completed_results_not_selected_options(
    client, app_bundle
) -> None:
    _, services = app_bundle
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with services.session_factory() as session:
        scan = Scan(
            id="retouched",
            created_at=now,
            original_filename="scan.png",
            width=100,
            height=100,
            files_deleted=True,
        )
        session.add(scan)
        session.flush()
        results = [
            ("ready", "crop|u1d0f1c0s0b1t1p1r1g1x2"),
            ("stale", "crop|scratch-v4|u0d1f0c1s1b0t0"),
            ("failed", "crop|u1f0c0s0"),  # Legacy upscale included denoise.
            ("running", "crop|u1d0f1c0s0b1t1"),  # Earlier successful result.
            ("queued", None),
            ("failed", None),
            ("none", None),  # Defaults/selected switches are not completed work.
            ("running", ""),
        ]
        for index, (status, signature) in enumerate(results):
            session.add(
                Region(
                    id=f"retouch-{index}",
                    scan_id=scan.id,
                    position=index,
                    center_x=50,
                    center_y=50,
                    width=20,
                    height=20,
                    angle_deg=0,
                    created_at=now,
                    updated_at=now,
                    retouch_status=status,
                    retouch_signature=signature,
                    # Deliberately different from the recorded result, and no local
                    # result paths: cleanup and later option edits must not alter counts.
                    retouch_upscale=False,
                    retouch_denoise=False,
                    retouch_faces=False,
                    retouch_colorize=False,
                    retouch_scratches=True,
                )
            )
        session.commit()

    response = client.get("/api/statistics")
    assert response.status_code == 200
    statistics = response.json()
    assert {key: value for key, value in statistics.items() if key.startswith("retouched")} == {
        "retouched": 4,
        "retouched_upscale": 3,
        "retouched_denoise": 2,
        "retouched_faces": 2,
        "retouched_colorize": 1,
        "retouched_scratches": 1,
        "retouched_color_balance": 2,
        "retouched_contrast": 2,
        "retouched_dust": 1,
        "retouched_deblur": 1,
        "retouched_gentle_denoise": 1,
    }
    assert client.delete("/api/scans/retouched").status_code == 204
    assert client.get("/api/statistics").json()["retouched"] == 0
