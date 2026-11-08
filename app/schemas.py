from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Visibility = Literal["timeline", "archive", "hidden"]


class StatisticsOut(BaseModel):
    scans: int
    scans_uploaded: int
    scans_cleaned_up: int
    detection_errors: int
    photos: int
    uploaded: int
    pending: int
    uploading: int
    failed: int
    with_date: int
    with_description: int
    with_album: int
    with_location: int
    favorites: int
    with_rating: int
    metadata_synced: int
    albums: int
    retouched: int
    retouched_upscale: int
    retouched_denoise: int
    retouched_faces: int
    retouched_colorize: int
    retouched_scratches: int
    retouched_color_balance: int
    retouched_contrast: int
    first_scan_at: datetime | None
    latest_scan_at: datetime | None
    earliest_photo_at: datetime | None
    latest_photo_at: datetime | None
    latest_upload_at: datetime | None


class RegionOut(BaseModel):
    id: str
    position: int
    center_x: float
    center_y: float
    width: float
    height: float
    angle_deg: float
    quarter_turns: int
    taken_at: datetime | None
    description: str
    album_id: str | None
    latitude: float | None
    longitude: float | None
    is_favorite: bool
    rating: int | None
    visibility: str | None
    upload_status: str
    immich_asset_id: str | None
    immich_status: str | None
    album_linked: bool
    metadata_synced: bool
    upload_error: str | None
    uploaded_at: datetime | None
    crop_changed: bool
    needs_upload: bool
    retouch_upscale: bool
    retouch_denoise: bool
    retouch_faces: bool
    retouch_colorize: bool
    retouch_scratches: bool
    retouch_color_balance: bool
    retouch_contrast: bool
    upload_source: Literal["crop", "retouch"]
    retouch_status: str
    retouch_progress: int | None = None
    retouch_stage: str | None = None
    retouch_error: str | None
    retouch_signature: str | None
    retouch_ready: bool
    retouch_version: str | None
    retouch_reconstructs_faces: bool
    updated_at: datetime


class ScanSummary(BaseModel):
    id: str
    created_at: datetime
    width: int
    height: int
    dpi: int | None
    device_name: str | None
    upload_state: str
    files_deleted: bool
    detection_error: str | None
    detecting: bool
    region_count: int
    uploaded_count: int
    original_filename: str


class ScanDetail(ScanSummary):
    regions: list[RegionOut]


class RegionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center_x: float
    center_y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    angle_deg: float = 0


class RegionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center_x: float | None = None
    center_y: float | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    angle_deg: float | None = None
    quarter_turns: int | None = Field(default=None, ge=0, le=3)
    taken_at: datetime | None = None
    description: str | None = Field(default=None, max_length=5000)
    album_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_favorite: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    visibility: Visibility | None = None
    retouch_upscale: bool | None = None
    retouch_denoise: bool | None = None
    retouch_faces: bool | None = None
    retouch_colorize: bool | None = None
    retouch_scratches: bool | None = None
    retouch_color_balance: bool | None = None
    retouch_contrast: bool | None = None
    upload_source: Literal["crop", "retouch"] | None = None

    @field_validator("album_id")
    @classmethod
    def _album_uuid(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        UUID(value)
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "RegionPatch":
        fields = self.model_fields_set
        geometry = {"center_x", "center_y", "width", "height", "angle_deg"}
        if fields & geometry and not geometry <= fields:
            raise ValueError("center, size, and angle must be sent together")
        location = {"latitude", "longitude"}
        if fields & location and location != (fields & location):
            raise ValueError("latitude and longitude must be updated together")
        if "latitude" in fields and (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be cleared")
        return self


class UploadRequest(BaseModel):
    region_ids: list[str] | None = None


class RetouchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upscale: bool = False
    denoise: bool = False
    faces: bool = False
    colorize: bool = False
    scratches: bool = False
    color_balance: bool = False
    contrast: bool = False

    @model_validator(mode="after")
    def _one_stage(self) -> "RetouchRequest":
        # Requests saved before denoise was its own field used upscale for both.
        if "denoise" not in self.model_fields_set:
            self.denoise = self.upscale
        if not any(
            (
                self.upscale,
                self.denoise,
                self.faces,
                self.colorize,
                self.scratches,
                self.color_balance,
                self.contrast,
            )
        ):
            raise ValueError("Choose at least one retouch stage.")
        return self


class RetouchQueued(BaseModel):
    job_id: str
    region: RegionOut


class ModelProgress(BaseModel):
    received: int
    total: int | None
    phase: Literal["downloading", "installing"]


class RetouchModelOut(BaseModel):
    id: str
    purpose: str
    version: str
    license_id: str
    license_summary: str
    source_url: str
    filename: str
    present: bool
    matches_pin: bool | None
    automatic_download: bool
    can_download: bool
    can_update: bool
    can_redownload: bool
    size_bytes: int | None
    progress: ModelProgress | None = None


class ModelFetch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept: bool = False
    force: bool = False


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    scan_id: str | None
    region_id: str | None
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SettingsOut(BaseModel):
    immich_base_url: str
    immich_api_key: str
    output_format: Literal["jpeg", "png"]
    jpeg_quality: int
    default_album_id: str
    device_name: str
    resolution_dpi: int
    scan_format: Literal["tiff", "png"]
    scan_mode: Literal["Color", "Gray"]
    width_mm: float | None
    height_mm: float | None
    retouch_upscale: bool
    retouch_denoise: bool
    retouch_faces: bool
    retouch_colorize: bool
    retouch_scratches: bool
    retouch_color_balance: bool
    retouch_contrast: bool


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    immich_base_url: str = ""
    immich_api_key: str = ""
    output_format: Literal["jpeg", "png"] = "jpeg"
    jpeg_quality: int = Field(default=95, ge=80, le=100)
    default_album_id: str = ""
    device_name: str = ""
    resolution_dpi: int = Field(default=300, ge=50, le=4800)
    scan_format: Literal["tiff", "png"] = "tiff"
    scan_mode: Literal["Color", "Gray"] = "Color"
    width_mm: float | None = Field(default=None, gt=0, le=400)
    height_mm: float | None = Field(default=None, gt=0, le=400)
    retouch_upscale: bool = False
    retouch_denoise: bool = False
    retouch_faces: bool = False
    retouch_colorize: bool = False
    retouch_scratches: bool = False
    retouch_color_balance: bool = False
    retouch_contrast: bool = False

    @model_validator(mode="after")
    def _legacy_denoise(self) -> "SettingsUpdate":
        if "retouch_denoise" not in self.model_fields_set:
            self.retouch_denoise = self.retouch_upscale
        return self

    @field_validator("default_album_id")
    @classmethod
    def _default_album(cls, value: str) -> str:
        if not value:
            return ""
        UUID(value)
        return value


class ConnectionTest(BaseModel):
    ok: bool
    version: str
    album_count: int


class AlbumOut(BaseModel):
    id: str
    name: str
    asset_count: int


class ScannerDeviceOut(BaseModel):
    name: str
    description: str


class ScannerStatusOut(BaseModel):
    phase: Literal["idle", "scanning", "saving"]
    phase_started_at: datetime | None
    phase_message: str
    scanner_found: bool
    scanner_message: str
    devices: list[ScannerDeviceOut]
    last_scan_ok: bool | None
    last_scan_message: str
    last_scan_id: str | None


class ScanStarted(BaseModel):
    status: Literal["started"] = "started"
