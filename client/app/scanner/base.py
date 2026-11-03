from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class ScannerDevice(BaseModel):
    name: str
    description: str


class ScanRequest(BaseModel):
    device_name: str = ""
    resolution_dpi: int = Field(ge=50, le=4800)
    image_format: str
    mode: str
    width_mm: float | None = None
    height_mm: float | None = None


class ScannerError(Exception):
    """The scanner could not list devices or capture a page."""


class Scanner(Protocol):
    def list_devices(self) -> list[ScannerDevice]:
        """Return scanners currently visible to this backend."""

    def scan(self, request: ScanRequest, destination: Path) -> None:
        """Capture the full bed into `destination`, overwriting it."""
