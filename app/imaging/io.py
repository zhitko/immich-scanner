from pathlib import Path

import cv2
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = 400_000_000


def as_float_rgb(image: np.ndarray) -> np.ndarray:
    """Working RGB is float32 in 0..255, including fractional scan levels."""
    return image.astype(np.float32) / (257.0 if image.dtype == np.uint16 else 1.0)


def as_byte_rgb(image: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(as_float_rgb(image)), 0, 255).astype(np.uint8)


def load_rgb(path: Path, *, working: bool = False) -> tuple[np.ndarray, int | None]:
    with Image.open(path) as image:
        dpi = _dpi(image)
        # Pillow silently reduces 16-bit RGB PNG/TIFF to eight bits. Decode
        # these with OpenCV, retaining Pillow for metadata and other modes.
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if decoded is not None and decoded.dtype == np.uint16:
            if decoded.ndim == 2:
                rgb = np.repeat(decoded[..., None], 3, axis=2)
            else:
                rgb = cv2.cvtColor(
                    decoded, cv2.COLOR_BGRA2RGB if decoded.shape[2] == 4 else cv2.COLOR_BGR2RGB
                )
        else:
            rgb = np.array(image.convert("RGB"))
        return (as_float_rgb(rgb) if working else as_byte_rgb(rgb)), dpi


def save_rgb(
    image: np.ndarray,
    path: Path,
    image_format: str,
    *,
    jpeg_quality: int = 95,
    exif: bytes | None = None,
    dpi: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    picture = Image.fromarray(as_byte_rgb(image), mode="RGB")
    options: dict[str, object] = {}
    if exif:
        options["exif"] = exif
    if dpi:
        options["dpi"] = (dpi, dpi)
    if image_format == "jpeg":
        picture.save(
            path,
            format="JPEG",
            quality=jpeg_quality,
            subsampling=0,
            optimize=True,
            **options,
        )
        return
    picture.save(path, format="PNG", **options)


def _dpi(image: Image.Image) -> int | None:
    raw = image.info.get("dpi")
    if isinstance(raw, tuple) and raw and raw[0]:
        return int(round(float(raw[0])))
    return None
