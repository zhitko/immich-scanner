from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Setting

OUTPUT_FORMATS = ("jpeg", "png")


@dataclass(frozen=True)
class ArchiveSettings:
    immich_base_url: str = ""
    immich_api_key: str = ""
    output_format: str = "jpeg"
    jpeg_quality: int = 95
    default_album_id: str = ""


def load_settings(session: Session) -> ArchiveSettings:
    rows = session.scalars(select(Setting)).all()
    stored = {row.key: row.value for row in rows}
    quality = stored.get("jpeg_quality", "95")
    try:
        jpeg_quality = int(quality)
    except ValueError:
        jpeg_quality = 95
    output_format = stored.get("output_format", "jpeg")
    if output_format not in OUTPUT_FORMATS:
        output_format = "jpeg"
    return ArchiveSettings(
        immich_base_url=stored.get("immich_base_url", ""),
        immich_api_key=stored.get("immich_api_key", ""),
        output_format=output_format,
        jpeg_quality=jpeg_quality,
        default_album_id=stored.get("default_album_id", ""),
    )


def save_settings(session: Session, settings: ArchiveSettings) -> None:
    values = {
        "immich_base_url": settings.immich_base_url.strip(),
        "immich_api_key": settings.immich_api_key.strip(),
        "output_format": settings.output_format,
        "jpeg_quality": str(settings.jpeg_quality),
        "default_album_id": settings.default_album_id.strip(),
    }
    for key, value in values.items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value


def seed_settings(session: Session, process: Settings) -> None:
    current = load_settings(session)
    seeded = ArchiveSettings(
        immich_base_url=current.immich_base_url or process.immich_base_url,
        immich_api_key=current.immich_api_key or process.immich_api_key,
        output_format=current.output_format,
        jpeg_quality=current.jpeg_quality,
        default_album_id=current.default_album_id,
    )
    if seeded != current or not session.get(Setting, "output_format"):
        save_settings(session, seeded)
