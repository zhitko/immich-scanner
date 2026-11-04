from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Album:
    id: str
    name: str
    asset_count: int


@dataclass(frozen=True)
class PhotoUpload:
    filename: str
    content: bytes
    content_type: str
    file_created_at: str
    file_modified_at: str
    sha1: str


@dataclass(frozen=True)
class AssetUploadResult:
    id: str
    status: str


@dataclass(frozen=True)
class AssetMetadata:
    description: str
    is_favorite: bool
    date_time_original: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: int | None = None
    visibility: str | None = None


class ImmichError(Exception):
    """Immich rejected a call or could not be reached."""


class ImmichGateway(Protocol):
    def server_version(self) -> str:
        """Return the Immich version string."""

    def list_albums(self) -> list[Album]:
        """Return albums visible to the API key."""

    def upload_asset(self, photo: PhotoUpload) -> AssetUploadResult:
        """Upload one file. A duplicate checksum still returns the existing id."""

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        """Add assets to one album."""

    def update_asset(self, asset_id: str, metadata: AssetMetadata) -> None:
        """Write description, date, rating, favorite, and location."""

    def close(self) -> None:
        """Release the underlying HTTP client when this gateway owns one."""
