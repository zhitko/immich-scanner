from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Region, Setting

OUTPUT_FORMATS = ("jpeg", "png")
SCAN_FORMATS = ("tiff", "png")
SCAN_MODES = ("Color", "Gray")


@dataclass(frozen=True)
class ArchiveSettings:
    immich_base_url: str = ""
    immich_api_key: str = ""
    output_format: str = "jpeg"
    jpeg_quality: int = 95
    default_album_id: str = ""
    default_visibility: str = ""
    device_name: str = ""
    resolution_dpi: int = 300
    scan_format: str = "tiff"
    scan_mode: str = "Color"
    width_mm: float | None = None
    height_mm: float | None = None
    retouch_upscale: bool = False
    retouch_denoise: bool = False
    retouch_faces: bool = False
    retouch_colorize: bool = False
    retouch_scratches: bool = False
    retouch_color_balance: bool = False
    retouch_contrast: bool = False
    retouch_dust: bool = False
    retouch_deblur: bool = False
    retouch_gentle_denoise: bool = False
    retouch_paper_mesh: bool = False
    retouch_paper_embossed: bool = False
    retouch_light_corners: bool = False
    retouch_output_scale: int = 4


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
    resolution = _int_in_range(stored.get("resolution_dpi", "300"), 300, 50, 4800)
    scan_format = stored.get("scan_format", "tiff")
    if scan_format not in SCAN_FORMATS:
        scan_format = "tiff"
    scan_mode = stored.get("scan_mode", "Color")
    if scan_mode not in SCAN_MODES:
        scan_mode = "Color"
    upscale = _flag(stored.get("retouch_upscale"))
    visibility = stored.get("default_visibility", "")
    if visibility not in ("", "timeline", "archive", "hidden"):
        visibility = ""
    return ArchiveSettings(
        immich_base_url=stored.get("immich_base_url", ""),
        immich_api_key=stored.get("immich_api_key", ""),
        output_format=output_format,
        jpeg_quality=jpeg_quality,
        default_album_id=stored.get("default_album_id", ""),
        default_visibility=visibility,
        device_name=stored.get("device_name", ""),
        resolution_dpi=resolution,
        scan_format=scan_format,
        scan_mode=scan_mode,
        width_mm=_optional_mm(stored.get("width_mm", "")),
        height_mm=_optional_mm(stored.get("height_mm", "")),
        retouch_upscale=upscale,
        retouch_denoise=_denoise(stored.get("retouch_denoise"), upscale),
        retouch_faces=_flag(stored.get("retouch_faces")),
        retouch_colorize=_flag(stored.get("retouch_colorize")),
        retouch_scratches=_flag(stored.get("retouch_scratches")),
        retouch_color_balance=_flag(stored.get("retouch_color_balance")),
        retouch_contrast=_flag(stored.get("retouch_contrast")),
        retouch_dust=_flag(stored.get("retouch_dust")),
        retouch_deblur=_flag(stored.get("retouch_deblur")),
        retouch_gentle_denoise=_flag(stored.get("retouch_gentle_denoise")),
        retouch_paper_mesh=_flag(stored.get("retouch_paper_mesh")),
        retouch_paper_embossed=_flag(stored.get("retouch_paper_embossed")),
        retouch_light_corners=_flag(stored.get("retouch_light_corners")),
        retouch_output_scale=2 if stored.get("retouch_output_scale") == "2" else 4,
    )


def save_settings(session: Session, settings: ArchiveSettings) -> None:
    values = {
        "immich_base_url": settings.immich_base_url.strip(),
        "immich_api_key": settings.immich_api_key.strip(),
        "output_format": settings.output_format,
        "jpeg_quality": str(settings.jpeg_quality),
        "default_album_id": settings.default_album_id.strip(),
        "default_visibility": settings.default_visibility,
        "device_name": settings.device_name.strip(),
        "resolution_dpi": str(settings.resolution_dpi),
        "scan_format": settings.scan_format,
        "scan_mode": settings.scan_mode,
        "width_mm": _format_mm(settings.width_mm),
        "height_mm": _format_mm(settings.height_mm),
        "retouch_upscale": _format_flag(settings.retouch_upscale),
        "retouch_denoise": _format_flag(settings.retouch_denoise),
        "retouch_faces": _format_flag(settings.retouch_faces),
        "retouch_colorize": _format_flag(settings.retouch_colorize),
        "retouch_scratches": _format_flag(settings.retouch_scratches),
        "retouch_color_balance": _format_flag(settings.retouch_color_balance),
        "retouch_contrast": _format_flag(settings.retouch_contrast),
        "retouch_dust": _format_flag(settings.retouch_dust),
        "retouch_deblur": _format_flag(settings.retouch_deblur),
        "retouch_gentle_denoise": _format_flag(settings.retouch_gentle_denoise),
        "retouch_paper_mesh": _format_flag(settings.retouch_paper_mesh),
        "retouch_paper_embossed": _format_flag(settings.retouch_paper_embossed),
        "retouch_light_corners": _format_flag(settings.retouch_light_corners),
        "retouch_output_scale": str(settings.retouch_output_scale),
    }
    for key, value in values.items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value


def seed_settings(session: Session, process: Settings) -> None:
    current = load_settings(session)
    resolution = current.resolution_dpi
    scan_format = current.scan_format
    if session.get(Setting, "resolution_dpi") is None:
        resolution = process.resolution_dpi
    if session.get(Setting, "scan_format") is None:
        scan_format = process.scan_format
    seeded = ArchiveSettings(
        immich_base_url=current.immich_base_url or process.immich_base_url,
        immich_api_key=current.immich_api_key or process.immich_api_key,
        output_format=current.output_format,
        jpeg_quality=current.jpeg_quality,
        default_album_id=current.default_album_id,
        default_visibility=current.default_visibility,
        device_name=current.device_name,
        resolution_dpi=resolution,
        scan_format=scan_format,
        scan_mode=current.scan_mode,
        width_mm=current.width_mm,
        height_mm=current.height_mm,
        retouch_upscale=current.retouch_upscale,
        retouch_denoise=current.retouch_denoise,
        retouch_faces=current.retouch_faces,
        retouch_colorize=current.retouch_colorize,
        retouch_scratches=current.retouch_scratches,
        retouch_color_balance=current.retouch_color_balance,
        retouch_contrast=current.retouch_contrast,
        retouch_dust=current.retouch_dust,
        retouch_deblur=current.retouch_deblur,
        retouch_gentle_denoise=current.retouch_gentle_denoise,
        retouch_paper_mesh=current.retouch_paper_mesh,
        retouch_paper_embossed=current.retouch_paper_embossed,
        retouch_light_corners=current.retouch_light_corners,
        retouch_output_scale=current.retouch_output_scale,
    )
    if seeded != current or not session.get(Setting, "output_format"):
        save_settings(session, seeded)


def _int_in_range(raw: str, fallback: int, low: int, high: int) -> int:
    try:
        value = int(raw)
    except ValueError:
        return fallback
    if not low <= value <= high:
        return fallback
    return value


def _optional_mm(raw: str) -> float | None:
    if not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not 0 < value <= 400:
        return None
    return value


def retouch_columns(settings: ArchiveSettings) -> dict[str, bool | int]:
    return {
        "retouch_upscale": settings.retouch_upscale,
        "retouch_denoise": settings.retouch_denoise,
        "retouch_faces": settings.retouch_faces,
        "retouch_colorize": settings.retouch_colorize,
        "retouch_scratches": settings.retouch_scratches,
        "retouch_color_balance": settings.retouch_color_balance,
        "retouch_contrast": settings.retouch_contrast,
        "retouch_dust": settings.retouch_dust,
        "retouch_deblur": settings.retouch_deblur,
        "retouch_gentle_denoise": settings.retouch_gentle_denoise,
        "retouch_paper_mesh": settings.retouch_paper_mesh,
        "retouch_paper_embossed": settings.retouch_paper_embossed,
        "retouch_light_corners": settings.retouch_light_corners,
        "retouch_output_scale": settings.retouch_output_scale,
    }


def apply_processing_defaults(region: Region, settings: ArchiveSettings) -> None:
    """Refresh editor defaults for a local photo without changing its history."""

    if region.immich_asset_id is None and not region.album_id and settings.default_album_id:
        region.album_id = settings.default_album_id
    if region.immich_asset_id is None and not region.visibility and settings.default_visibility:
        region.visibility = settings.default_visibility

    if region.retouch_status not in {"none", "failed"}:
        return
    if region.retouch_path or region.retouch_signature:
        return
    for key, value in retouch_columns(settings).items():
        setattr(region, key, value)


def _flag(raw: str | None) -> bool:
    return raw == "true"


def _denoise(raw: str | None, upscale: bool) -> bool:
    """A settings file from before the split stored only the combined step."""

    if raw is None:
        return upscale
    return raw == "true"


def _format_flag(value: bool) -> str:
    return "true" if value else "false"


def _format_mm(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"
