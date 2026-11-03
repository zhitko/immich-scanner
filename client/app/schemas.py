from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceOut(BaseModel):
    name: str
    description: str


class ClientSettings(BaseModel):
    server_url: str = "http://127.0.0.1:8000"
    api_token: str = ""
    device_name: str = ""
    resolution_dpi: int = Field(default=300, ge=50, le=4800)
    image_format: Literal["tiff", "png"] = "tiff"
    mode: Literal["Color", "Gray"] = "Color"
    width_mm: float | None = Field(default=None, gt=0, le=400)
    height_mm: float | None = Field(default=None, gt=0, le=400)


class ClientSettingsUpdate(BaseModel):
    server_url: str
    api_token: str = ""
    device_name: str = ""
    resolution_dpi: int = Field(ge=50, le=4800)
    image_format: Literal["tiff", "png"] = "tiff"
    mode: Literal["Color", "Gray"] = "Color"
    width_mm: float | None = Field(default=None, gt=0, le=400)
    height_mm: float | None = Field(default=None, gt=0, le=400)

    def to_settings(self) -> ClientSettings:
        return ClientSettings.model_validate(self.model_dump())


class StatusOut(BaseModel):
    phase: Literal["idle", "scanning", "uploading"]
    phase_message: str
    scanner_found: bool
    scanner_message: str
    devices: list[DeviceOut]
    server_reachable: bool
    server_message: str
    last_scan_at: datetime | None
    last_scan_ok: bool | None
    last_scan_message: str
    last_scan_id: str | None


class ScanAccepted(BaseModel):
    status: Literal["started"] = "started"
