import hashlib
from dataclasses import replace

import httpx
import pytest
from starlette.testclient import TestClient

from app.immich.client import ImmichClient
from app.immich.gateway import AssetMetadata, ImmichError, PhotoUpload
from mock_immich.app import FAMILY_ALBUM, STORE, create_mock_app, reset_store


def test_client_matches_the_v3_asset_contract() -> None:
    reset_store()
    http = TestClient(create_mock_app(), base_url="http://immich/api")
    client = ImmichClient("http://unused.example", "test-key", http=http)
    assert client.server_version() == "3.3.5"
    names = {album.name for album in client.list_albums()}
    assert names == {"Family", "Trips"}

    content = b"not-a-real-jpeg-but-bytes"
    photo = PhotoUpload(
        filename="print.jpg",
        content=content,
        content_type="image/jpeg",
        file_created_at="1999-01-02T03:04:05.000Z",
        file_modified_at="1999-01-02T03:04:05.000Z",
        sha1=hashlib.sha1(content).hexdigest(),
    )
    created = client.upload_asset(photo)
    assert created.status == "created"
    assert STORE.last_api_key == "test-key"
    duplicate = client.upload_asset(photo)
    assert duplicate.status == "duplicate"
    assert duplicate.id == created.id

    client.update_asset(
        created.id,
        AssetMetadata(
            description="Aunt Mae",
            is_favorite=True,
            date_time_original="1999-01-02T03:04:05.000Z",
            latitude=41.0,
            longitude=-73.5,
            rating=5,
            visibility="archive",
        ),
    )
    client.add_assets_to_album(FAMILY_ALBUM, [created.id])
    stored = STORE.assets[created.id]
    assert stored["description"] == "Aunt Mae"
    assert stored["isFavorite"] is True
    assert stored["visibility"] == "archive"
    assert created.id in STORE.albums[FAMILY_ALBUM]["assetIds"]
    details = client.get_asset(created.id)
    assert details.metadata.description == "Aunt Mae"
    assert details.metadata.visibility == "archive"
    assert details.metadata.latitude == 41.0
    assert details.album_ids == [FAMILY_ALBUM]
    client.close()


@pytest.mark.parametrize("error_field", ["error", "errorMessage"])
def test_album_add_accepts_existing_membership(error_field: str) -> None:
    def respond(request):
        assert request.method == "PUT"
        assert request.url.path == "/api/albums/album/assets"
        return httpx.Response(200, json=[
            {"id": "existing", "success": False, error_field: "duplicate"},
            {"id": "new", "success": True},
        ])

    with httpx.Client(
        base_url="http://immich/api", transport=httpx.MockTransport(respond)
    ) as http:
        client = ImmichClient("http://unused.example", "test-key", http=http)
        client.add_assets_to_album("album", ["existing", "new"])


@pytest.mark.parametrize("error_field", ["error", "errorMessage"])
@pytest.mark.parametrize("reason", ["not_found", "no_permission", None])
def test_album_add_still_rejects_other_failures(error_field: str, reason: str | None) -> None:
    def respond(request):
        return httpx.Response(200, json=[
            {"id": "existing", "success": False, "error": "duplicate"},
            {"id": "failed", "success": False, error_field: reason},
        ])

    with httpx.Client(
        base_url="http://immich/api", transport=httpx.MockTransport(respond)
    ) as http:
        client = ImmichClient("http://unused.example", "test-key", http=http)
        with pytest.raises(ImmichError, match=reason or "unknown"):
            client.add_assets_to_album("album", ["existing", "failed"])


def test_mock_rejects_an_upload_missing_required_fields() -> None:
    reset_store()
    http = TestClient(create_mock_app(), base_url="http://immich/api")
    response = http.post(
        "/assets",
        headers={"x-api-key": "test-key"},
        files={"assetData": ("a.jpg", b"abc", "image/jpeg")},
    )
    assert response.status_code == 400
    missing = http.get("/albums")
    assert missing.status_code == 401


def test_replacement_copies_albums_and_trashes_old_asset() -> None:
    reset_store()
    http = TestClient(create_mock_app(), base_url="http://immich/api")
    client = ImmichClient("http://unused.example", "test-key", http=http)
    photo = PhotoUpload(
        filename="print.jpg", content=b"original", content_type="image/jpeg",
        file_created_at="1999-01-02T03:04:05.000Z",
        file_modified_at="1999-01-02T03:04:05.000Z",
        sha1=hashlib.sha1(b"original").hexdigest(),
    )
    original = client.upload_asset(photo)
    client.add_assets_to_album(FAMILY_ALBUM, [original.id])
    identical = client.replace_asset(original.id, photo)
    assert identical.id == original.id
    assert not STORE.assets[original.id].get("isTrashed")

    changed = replace(photo, content=b"replacement", sha1=hashlib.sha1(b"replacement").hexdigest())
    replacement = client.replace_asset(original.id, changed)
    assert replacement.id != original.id
    assert STORE.assets[replacement.id]["bytes"] == b"replacement"
    assert replacement.id in STORE.albums[FAMILY_ALBUM]["assetIds"]
    assert STORE.assets[original.id]["isTrashed"] is True


@pytest.mark.parametrize("failure", ["upload", "copy"])
def test_failed_replacement_does_not_delete_old_asset(failure) -> None:
    calls = []

    def respond(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "old"})
        if request.method == "POST" and failure != "upload":
            return httpx.Response(201, json={"id": "new", "status": "created"})
        if request.method == "PUT":
            return httpx.Response(400, json={"message": "Not found or no asset.copy access"})
        return httpx.Response(500, text="failed")

    http = httpx.Client(base_url="http://immich/api", transport=httpx.MockTransport(respond))
    client = ImmichClient("http://unused.example", "test-key", http=http)
    photo = PhotoUpload("a.jpg", b"a", "image/jpeg", "date", "date", "checksum")
    with pytest.raises(ImmichError):
        client.replace_asset("old", photo)
    assert "DELETE" not in calls


@pytest.mark.parametrize("status", [400, 404])
def test_reupload_when_previous_asset_was_deleted(status) -> None:
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(201, json={"id": "new", "status": "created"})
        if request.method == "GET":
            return httpx.Response(status, json={"message": "Not found or no asset.read access"})
        pytest.fail("A deleted asset must not be copied or deleted again")

    with httpx.Client(
        base_url="http://immich/api", transport=httpx.MockTransport(respond)
    ) as http:
        client = ImmichClient("http://unused.example", "test-key", http=http)
        photo = PhotoUpload("a.jpg", b"a", "image/jpeg", "date", "date", "checksum")
        result = client.replace_asset("deleted", photo)
    assert result.id == "new"
    assert calls == [("POST", "/api/assets"), ("GET", "/api/assets/deleted")]
