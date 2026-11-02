import cv2
import numpy as np

from app.imaging.crop import rotated_rect_corners


def paint_photo(
    image: np.ndarray,
    color: tuple[int, int, int],
    center: tuple[float, float],
    size: tuple[float, float],
    angle: float,
    border: int = 10,
    border_color: tuple[int, int, int] = (16, 16, 16),
) -> None:
    outer = rotated_rect_corners(center[0], center[1], size[0], size[1], angle)
    inner_w = max(1.0, size[0] - border * 2)
    inner_h = max(1.0, size[1] - border * 2)
    inner = rotated_rect_corners(center[0], center[1], inner_w, inner_h, angle)
    cv2.fillConvexPoly(image, np.round(outer).astype(np.int32), border_color)
    cv2.fillConvexPoly(image, np.round(inner).astype(np.int32), color)


def make_bed(
    size: tuple[int, int] = (1000, 1400),
    background: tuple[int, int, int] = (250, 250, 248),
    photos: list[dict[str, object]] | None = None,
    speck: bool = True,
) -> np.ndarray:
    width, height = size
    image = np.full((height, width, 3), background, np.uint8)
    if photos is None:
        photos = [
            {"color": (180, 40, 50), "center": (280, 240), "size": (340, 220), "angle": -12},
            {"color": (40, 90, 170), "center": (720, 620), "size": (300, 200), "angle": 0},
            {"color": (40, 140, 80), "center": (420, 1080), "size": (380, 240), "angle": 15},
        ]
    for photo in photos:
        paint_photo(
            image,
            photo["color"],  # type: ignore[arg-type]
            photo["center"],  # type: ignore[arg-type]
            photo["size"],  # type: ignore[arg-type]
            float(photo["angle"]),
        )
    if speck:
        speck_color = (8, 8, 8) if background[0] > 40 else (245, 245, 245)
        image[height - 18 : height - 8, width - 18 : width - 8] = speck_color
    return image


def encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("could not encode png")
    return encoded.tobytes()
