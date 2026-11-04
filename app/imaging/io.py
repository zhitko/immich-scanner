from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = 400_000_000


def load_rgb(path: Path) -> tuple[np.ndarray, int | None]:
    with Image.open(path) as image:
        dpi = _dpi(image)
        if image.mode.startswith("I;16") or image.mode == "I":
            array = np.asarray(image).astype(np.uint32)
            eight = np.clip(array >> 8, 0, 255).astype(np.uint8)
            return np.stack([eight, eight, eight], axis=-1), dpi
        return np.array(image.convert("RGB")), dpi


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
    picture = Image.fromarray(image, mode="RGB")
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
