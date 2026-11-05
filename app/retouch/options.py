import re
from dataclasses import dataclass

from app.imaging.crop import crop_signature
from app.models import Region

_FLAGS = re.compile(r"u([01])f([01])c([01])s([01])$")
_RETOUCH_MARKER = "|retouch|"


@dataclass(frozen=True)
class RetouchOptions:
    upscale: bool = False
    faces: bool = False
    colorize: bool = False
    scratches: bool = False

    def any_selected(self) -> bool:
        return self.upscale or self.faces or self.colorize or self.scratches


def options_from_region(region: Region) -> RetouchOptions:
    return RetouchOptions(
        upscale=bool(region.retouch_upscale),
        faces=bool(region.retouch_faces),
        colorize=bool(region.retouch_colorize),
        scratches=bool(region.retouch_scratches),
    )


def option_token(options: RetouchOptions) -> str:
    return (
        f"u{int(options.upscale)}"
        f"f{int(options.faces)}"
        f"c{int(options.colorize)}"
        f"s{int(options.scratches)}"
    )


def geometry_signature(region: Region) -> str:
    return crop_signature(
        region.center_x,
        region.center_y,
        region.width,
        region.height,
        region.angle_deg,
        region.quarter_turns,
    )


def expected_retouch_signature(region: Region) -> str:
    return f"{geometry_signature(region)}|{option_token(options_from_region(region))}"


def content_signature(region: Region) -> str:
    base = geometry_signature(region)
    if region.upload_source == "retouch":
        return f"{base}{_RETOUCH_MARKER}{region.retouch_signature or ''}"
    return base


def stored_geometry(signature: str | None) -> str:
    if not signature:
        return ""
    if _RETOUCH_MARKER in signature:
        return signature.split(_RETOUCH_MARKER, 1)[0]
    return signature


def flags_restore_faces(signature: str | None) -> bool:
    if not signature:
        return False
    match = _FLAGS.search(signature)
    return bool(match and match.group(2) == "1")


def retouch_is_current(region: Region) -> bool:
    return (
        region.retouch_status == "ready"
        and bool(region.retouch_path)
        and region.retouch_signature == expected_retouch_signature(region)
    )


def sync_retouch_status(region: Region) -> None:
    """Mark a finished derivative stale when the crop or the switches no longer match."""

    if region.retouch_status in {"queued", "running"}:
        return
    if not region.retouch_signature and not region.retouch_path:
        return
    if retouch_matches(region):
        region.retouch_status = "ready"
        region.retouch_error = None
        return
    region.retouch_status = "stale"
    region.retouch_error = None
    if region.upload_source == "retouch":
        region.upload_source = "crop"


def retouch_matches(region: Region) -> bool:
    return bool(region.retouch_path) and region.retouch_signature == expected_retouch_signature(
        region
    )
