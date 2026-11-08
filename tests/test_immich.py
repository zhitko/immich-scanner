import hashlib

from starlette.testclient import TestClient

from app.immich.client import ImmichClient
from app.immich.gateway import AssetMetadata, PhotoUpload
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
