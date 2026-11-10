from contextlib import suppress

import httpx

from app.immich.gateway import (
    Album,
    AssetDetails,
    AssetMetadata,
    AssetUploadResult,
    ImmichError,
    PhotoUpload,
)

_UPDATE_FIELDS = {
    "dateTimeOriginal",
    "description",
    "isFavorite",
    "latitude",
    "longitude",
    "rating",
    "visibility",
}


class ImmichClient:
    """Calls the Immich API as published for v3.3.5.

    Upload is ``POST /api/assets`` (multipart ``assetData``, ``fileCreatedAt``,
    ``fileModifiedAt``, optional ``x-immich-checksum``). Metadata is
    ``PUT /api/assets/{id}`` with ``UpdateAssetDto``. Album membership is
    ``PUT /api/albums/{id}/assets`` with ``{"ids": [...]}``. The API key is the
    ``x-api-key`` header. ``PUT /api/assets/{id}`` is marked deprecated in the
    v3.3.5 spec but is still the only update operation that spec defines.
    """

    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None) -> None:
        self._api_key = api_key.strip()
        if not self._api_key:
            raise ImmichError("Immich API key is empty")
        if http is None:
            self._http = httpx.Client(
                base_url=api_base(base_url),
                timeout=httpx.Timeout(180, connect=10),
            )
            self._owns_client = True
        else:
            self._http = http
            self._owns_client = False

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def server_version(self) -> str:
        payload = self._json("GET", "/server/version")
        prerelease = payload.get("prerelease")
        version = f"{payload['major']}.{payload['minor']}.{payload['patch']}"
        if prerelease is not None:
            return f"{version}-pre.{prerelease}"
        return version

    def list_albums(self) -> list[Album]:
        payload = self._json("GET", "/albums")
        if not isinstance(payload, list):
            raise ImmichError("album list was not a JSON array")
        albums: list[Album] = []
        for item in payload:
            albums.append(
                Album(
                    id=str(item["id"]),
                    name=str(item.get("albumName") or ""),
                    asset_count=int(item.get("assetCount") or 0),
                )
            )
        return albums

    def upload_asset(self, photo: PhotoUpload) -> AssetUploadResult:
        response = self._request(
            "POST",
            "/assets",
            data={
                "fileCreatedAt": photo.file_created_at,
                "fileModifiedAt": photo.file_modified_at,
                "filename": photo.filename,
            },
            files={"assetData": (photo.filename, photo.content, photo.content_type)},
            headers={"x-immich-checksum": photo.sha1},
        )
        if response.status_code not in {200, 201}:
            raise ImmichError(f"upload failed: {response.status_code} {response.text[:300]}")
        body = response.json()
        return AssetUploadResult(id=str(body["id"]), status=str(body.get("status") or ""))

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        body = self._json("PUT", f"/albums/{album_id}/assets", json={"ids": asset_ids})
        if not isinstance(body, list):
            raise ImmichError("album update did not return a result list")
        # Reuploads may reuse an existing asset or copy its album memberships.
        # An asset already in the album satisfies the requested operation.
        failed = [
            item
            for item in body
            if not item.get("success", False)
            and (item.get("error") or item.get("errorMessage")) != "duplicate"
        ]
        if failed:
            reason = failed[0].get("error") or failed[0].get("errorMessage") or "unknown"
            raise ImmichError(f"could not add the asset to the album ({reason})")

    def replace_asset(self, asset_id: str, photo: PhotoUpload) -> AssetUploadResult:
        result = self.upload_asset(photo)
        if result.id != asset_id:
            previous = self._request("GET", f"/assets/{asset_id}")
            # Immich uses 400 for missing assets as well as 404. Do not treat
            # unrelated validation or server errors as a deleted source asset.
            missing = previous.status_code == 404
            if previous.status_code == 400:
                with suppress(ValueError, AttributeError):
                    missing = previous.json().get("message") == "Not found or no asset.read access"
            if missing:
                return result
            if previous.status_code >= 400:
                raise ImmichError(
                    f"GET /assets/{asset_id} failed: "
                    f"{previous.status_code} {previous.text[:300]}"
                )
            self._json(
                "PUT", "/assets/copy", json={"sourceId": asset_id, "targetId": result.id}
            )
            # Only trash the old version after the upload and association copy succeed.
            self._json("DELETE", "/assets", json={"ids": [asset_id], "force": False})
        return result

    def update_asset(self, asset_id: str, metadata: AssetMetadata) -> None:
        payload: dict[str, object] = {
            "description": metadata.description,
            "isFavorite": metadata.is_favorite,
        }
        if metadata.date_time_original:
            payload["dateTimeOriginal"] = metadata.date_time_original
        if metadata.latitude is not None and metadata.longitude is not None:
            payload["latitude"] = metadata.latitude
            payload["longitude"] = metadata.longitude
        if metadata.rating is not None:
            payload["rating"] = metadata.rating
        if metadata.visibility:
            payload["visibility"] = metadata.visibility
        unknown = set(payload) - _UPDATE_FIELDS
        if unknown:
            raise ImmichError(f"refusing to send unknown asset fields: {sorted(unknown)}")
        self._json("PUT", f"/assets/{asset_id}", json=payload)

    def get_asset(self, asset_id: str) -> AssetDetails:
        asset = self._json("GET", f"/assets/{asset_id}")
        albums = self._json("GET", "/albums", params={"assetId": asset_id})
        if not isinstance(asset, dict) or not isinstance(albums, list):
            raise ImmichError("invalid asset or album response from Immich")
        exif = asset.get("exifInfo") or {}
        if not isinstance(exif, dict):
            raise ImmichError("invalid asset metadata from Immich")
        try:
            return AssetDetails(
                metadata=AssetMetadata(
                    description=exif.get("description") or "",
                    is_favorite=asset.get("isFavorite", False),
                    date_time_original=exif.get("dateTimeOriginal"),
                    latitude=exif.get("latitude"),
                    longitude=exif.get("longitude"),
                    rating=exif.get("rating"),
                    visibility=asset.get("visibility"),
                ),
                album_ids=[str(album["id"]) for album in albums],
            )
        except (KeyError, TypeError) as exc:
            raise ImmichError("invalid album response from Immich") from exc

    def _json(self, method: str, path: str, **kwargs: object) -> object:
        response = self._request(method, path, **kwargs)
        if response.status_code >= 400:
            detail = response.text[:300]
            raise ImmichError(f"{method} {path} failed: {response.status_code} {detail}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})  # type: ignore[arg-type]
        headers["x-api-key"] = self._api_key
        headers.setdefault("Accept", "application/json")
        try:
            return self._http.request(method, path, headers=headers, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise ImmichError(f"could not reach Immich: {exc}") from exc


def api_base(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ImmichError("Immich URL is empty")
    if cleaned.endswith("/api"):
        return cleaned
    return cleaned + "/api"
