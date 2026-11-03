from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. User-facing scanner settings live in a JSON file."""

    data_dir: Path = Path("data")
    scanner_backend: Literal["sane", "fake"] = "sane"
    host: str = "0.0.0.0"
    port: int = 8080
    server_url: str = "http://127.0.0.1:8000"
    api_token: str = ""
    resolution_dpi: int = 300
    image_format: Literal["tiff", "png"] = "tiff"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
