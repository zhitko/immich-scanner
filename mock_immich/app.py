import hashlib
import re
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

FAMILY_ALBUM = "11111111-1111-4111-8111-111111111111"
TRIPS_ALBUM = "22222222-2222-4222-8222-222222222222"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_UPDATE_FIELDS = {
    "dateTimeOriginal",
    "description",
    "isFavorite",
    "latitude",
    "livePhotoVideoId",
    "longitude",
    "rating",
    "visibility",
}
_VISIBILITY = {"archive", "timeline", "hidden", "locked"}


class BulkIds(BaseModel):
    ids: list[str]


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dateTimeOriginal: str | None = None
    description: str | None = None
    isFavorite: bool | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rating: int | None = Field(default=None, ge=-1, le=5)
    visibility: str | None = None
    livePhotoVideoId: str | None = None


class MemoryStore:
    def __init__(self) -> None:
        self.assets: dict[str, dict[str, object]] = {}
        self.by_checksum: dict[str, str] = {}
        self.albums: dict[str, dict[str, object]] = {
            FAMILY_ALBUM: {"id": FAMILY_ALBUM, "albumName": "Family", "assetIds": set()},
            TRIPS_ALBUM: {"id": TRIPS_ALBUM, "albumName": "Trips", "assetIds": set()},
        }
        self.last_api_key: str | None = None

    def reset(self) -> None:
        self.__init__()


STORE = MemoryStore()


def create_mock_app() -> FastAPI:
    app = FastAPI(title="mock-immich", version="3.3.5")

    @app.get("/api/server/ping")
    def ping() -> dict[str, str]:
        return {"res": "pong"}

    @app.get("/api/server/version")
    def version() -> dict[str, int | None]:
        return {"major": 3, "minor": 3, "patch": 5, "prerelease": None}

    @app.get("/api/albums")
    def albums(
        assetId: str | None = None, x_api_key: str | None = Header(default=None)
    ) -> list[dict[str, object]]:
        _require_key(x_api_key)
        return [
            {
                "id": album["id"],
                "albumName": album["albumName"],
                "assetCount": len(album["assetIds"]),
                "description": "",
            }
            for album in STORE.albums.values()
            if assetId is None or assetId in album["assetIds"]
        ]

    @app.post("/api/assets")
    async def upload_asset(
        request: Request,
        assetData: UploadFile | None = File(default=None),
        fileCreatedAt: str | None = Form(default=None),
        fileModifiedAt: str | None = Form(default=None),
        filename: str | None = Form(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, str]:
        _require_key(x_api_key)
        if assetData is None or not fileCreatedAt or not fileModifiedAt:
            raise HTTPException(
                status_code=400,
                detail="assetData, fileCreatedAt, and fileModifiedAt are required",
            )
        if _ISO.match(fileCreatedAt) is None or _ISO.match(fileModifiedAt) is None:
            raise HTTPException(
                status_code=400,
                detail="file dates must be ISO-8601 with a timezone",
            )
        content = await assetData.read()
        if not content:
            raise HTTPException(status_code=400, detail="assetData is empty")
        checksum = request.headers.get("x-immich-checksum")
        digest = hashlib.sha1(content).hexdigest()
        if checksum and checksum != digest:
            raise HTTPException(status_code=400, detail="x-immich-checksum does not match the file")
        existing = STORE.by_checksum.get(digest)
        if existing:
            return JSONResponse({"id": existing, "status": "duplicate"}, status_code=200)
        asset_id = str(uuid4())
        STORE.assets[asset_id] = {
            "id": asset_id,
            "filename": filename or assetData.filename,
            "bytes": content,
            "checksum": digest,
            "fileCreatedAt": fileCreatedAt,
            "fileModifiedAt": fileModifiedAt,
            "description": "",
            "isFavorite": False,
        }
        STORE.by_checksum[digest] = asset_id
        return JSONResponse({"id": asset_id, "status": "created"}, status_code=201)

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str, x_api_key: str | None = Header(default=None)) -> dict[str, object]:
        _require_key(x_api_key)
        asset = STORE.assets.get(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return {
            "id": asset_id,
            "isFavorite": asset["isFavorite"],
            "visibility": asset.get("visibility", "timeline"),
            "exifInfo": {key: asset.get(key) for key in (
                "description", "dateTimeOriginal", "latitude", "longitude", "rating"
            )},
        }

    @app.put("/api/assets/{asset_id}")
    def update_asset(
        asset_id: str,
        body: AssetUpdate,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_key(x_api_key)
        asset = STORE.assets.get(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="asset not found")
        unknown = set(body.model_fields_set) - _UPDATE_FIELDS
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown fields: {sorted(unknown)}")
        if body.visibility is not None and body.visibility not in _VISIBILITY:
            raise HTTPException(status_code=400, detail="invalid visibility")
        if body.rating == 0:
            raise HTTPException(status_code=400, detail="rating 0 is not valid")
        for field in body.model_fields_set:
            asset[field] = getattr(body, field)
        return {"id": asset_id}

    @app.put("/api/albums/{album_id}/assets")
    def add_assets(
        album_id: str,
        body: BulkIds,
        x_api_key: str | None = Header(default=None),
    ) -> list[dict[str, object]]:
        _require_key(x_api_key)
        album = STORE.albums.get(album_id)
        if album is None:
            raise HTTPException(status_code=404, detail="album not found")
        results = []
        for asset_id in body.ids:
            if asset_id not in STORE.assets:
                results.append({"id": asset_id, "success": False, "error": "not_found"})
                continue
            asset_ids = album["assetIds"]
            if isinstance(asset_ids, set):
                asset_ids.add(asset_id)
            results.append({"id": asset_id, "success": True})
        return results

    return app


def reset_store() -> None:
    STORE.reset()


def _require_key(api_key: str | None) -> None:
    if not api_key:
        raise HTTPException(status_code=401, detail="missing x-api-key")
    STORE.last_api_key = api_key
