import re
from dataclasses import dataclass

from app.imaging.crop import crop_signature
from app.models import Region

# The denoise bit is optional. A saved token without it is the old combined
# "upscale and denoise" step, so that bit follows the upscale bit.
_TOKEN = re.compile(r"u([01])(?:d([01]))?f([01])c([01])s([01])(?:b([01])t([01]))?$")
_RETOUCH_MARKER = "|retouch|"


@dataclass(frozen=True)
class RetouchOptions:
    upscale: bool = False
    denoise: bool = False
    faces: bool = False
    colorize: bool = False
    scratches: bool = False
    color_balance: bool = False
    contrast: bool = False

    def any_selected(self) -> bool:
        return any(
            (
                self.upscale,
                self.denoise,
                self.faces,
                self.colorize,
                self.scratches,
                self.color_balance,
                self.contrast,
            )
        )


def options_from_region(region: Region) -> RetouchOptions:
    return RetouchOptions(
        upscale=bool(region.retouch_upscale),
        denoise=bool(region.retouch_denoise),
        faces=bool(region.retouch_faces),
        colorize=bool(region.retouch_colorize),
        scratches=bool(region.retouch_scratches),
        color_balance=bool(region.retouch_color_balance),
        contrast=bool(region.retouch_contrast),
    )


def option_token(options: RetouchOptions) -> str:
    return (
        f"u{int(options.upscale)}"
        f"d{int(options.denoise)}"
        f"f{int(options.faces)}"
        f"c{int(options.colorize)}"
        f"s{int(options.scratches)}"
        f"b{int(options.color_balance)}"
        f"t{int(options.contrast)}"
    )


def options_from_token(token: str) -> RetouchOptions | None:
    match = _TOKEN.fullmatch(token)
    if match is None:
        return None
    upscale = match.group(1) == "1"
    denoise_bit = match.group(2)
    return RetouchOptions(
        upscale=upscale,
        denoise=upscale if denoise_bit is None else denoise_bit == "1",
        faces=match.group(3) == "1",
        colorize=match.group(4) == "1",
        scratches=match.group(5) == "1",
        color_balance=match.group(6) == "1",
        contrast=match.group(7) == "1",
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
    parsed = options_from_token(signature.rpartition("|")[2])
    return bool(parsed and parsed.faces)


def retouch_is_current(region: Region) -> bool:
    return region.retouch_status == "ready" and retouch_matches(region)


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
    if not region.retouch_path or not region.retouch_signature:
        return False
    if region.retouch_signature == expected_retouch_signature(region):
        return True
    # A derivative from before denoise was its own bit stays current when the
    # saved upscale bit still means both steps and the crop is unchanged.
    prefix, _separator, token = region.retouch_signature.rpartition("|")
    stored = options_from_token(token)
    return stored == options_from_region(region) and prefix == geometry_signature(region)
