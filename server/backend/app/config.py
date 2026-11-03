from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    database_url: str = ""
    scanner_api_token: str = "change-me"
    immich_base_url: str = ""
    immich_api_key: str = ""
    static_dir: Path = Path("static")
    host: str = "0.0.0.0"
    port: int = 8000
    worker_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def sqlite_url(self) -> str:
        if self.database_url:
            return self.database_url
        return "sqlite:///" + str((self.data_dir / "immich-scanner.db").resolve())


@lru_cache
def get_settings() -> Settings:
    return Settings()
