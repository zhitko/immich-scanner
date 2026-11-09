from collections.abc import Callable

import cv2
import numpy as np

# GFPGAN's 512 template: image-left eye, image-right eye, nose, image-left mouth, image-right mouth.
# YuNet lists the person's right eye first, which is the image-left eye on a frontal photo.
FACE_TEMPLATE = np.array(
    [
        [192.98138, 239.94708],
        [318.90277, 240.1936],
        [256.63416, 314.01935],
        [201.26117, 371.41043],
        [313.08905, 371.15118],
    ],
    dtype=np.float32,
)


def tiled_map(
    image: np.ndarray,
    run: Callable[[np.ndarray], np.ndarray],
    *,
    tile: int,
    overlap: int,
    on_tile: Callable[[], None] | None = None,
) -> np.ndarray:
    """Run `run` on tiles and stitch. `run` returns the same scale for every tile.

    Blending happens one row of tiles at a time to bound temporary allocations.
    """

    if tile < 1:
        raise ValueError("tile must be positive")
    height, width = image.shape[:2]
    work_h, work_w, overlap, starts_y, starts_x = _grid(height, width, tile, tile, overlap)
    working = _pad(image, work_h, work_w)
    sample = run(working[:tile, :tile])
    scale_y, scale_x = _scale((tile, tile), sample.shape)
    if scale_y != scale_x:
        raise RuntimeError("upscaler scale is not square")
    scale = scale_y
    size = tile * scale
    channels = image.shape[2]
    stitched = np.empty((work_h * scale, work_w * scale, channels), dtype=sample.dtype)
    window = _window(tile, overlap, scale)
    carried: tuple[np.ndarray, np.ndarray] | None = None
    for row, y in enumerate(starts_y):
        strip = np.zeros((size, work_w * scale, channels), dtype=np.float32)
        weights = np.zeros((size, work_w * scale, 1), dtype=np.float32)
        if carried is not None:
            rows = carried[0].shape[0]
            strip[:rows] += carried[0]
            weights[:rows] += carried[1]
        for x in starts_x:
            output = sample if row == 0 and x == 0 else run(working[y : y + tile, x : x + tile])
            if on_tile is not None:
                on_tile()
            if output.shape[0] != size or output.shape[1] != size:
                raise RuntimeError("upscaler tiles disagree on scale")
            origin_x = x * scale
            strip[:, origin_x : origin_x + size] += output.astype(np.float32) * window
            weights[:, origin_x : origin_x + size] += window
        done = (starts_y[row + 1] - y) * scale if row + 1 < len(starts_y) else size
        top = y * scale
        normalized = _normalize(strip[:done], weights[:done])
        stitched[top : top + done] = (
            np.rint(normalized) if stitched.dtype == np.uint8 else normalized
        )
        carried = (strip[done:], weights[done:])
    return stitched[: height * scale, : width * scale]


def square_tile_count(height: int, width: int, tile: int, overlap: int) -> int:
    """How many tiles `tiled_map` will run, including the first sample tile."""

    _work_h, _work_w, _overlap, starts_y, starts_x = _grid(height, width, tile, tile, overlap)
    return len(starts_y) * len(starts_x)


def masked_tiles(
    image: np.ndarray,
    mask: np.ndarray,
    run: Callable[[np.ndarray, np.ndarray], np.ndarray],
    *,
    tile_h: int,
    tile_w: int,
    overlap: int,
    on_tile: Callable[[], None] | None = None,
) -> np.ndarray:
    """Run `run(tile, tile_mask)` at full resolution on each tile that holds a masked pixel.

    `tile_mask` is uint8 with 1 marking the hole. Only masked pixels take the output.
    Where tiles overlap, their fills are cross-faded, so a hole that spans two tiles
    has no seam where one tile's guess meets the next.
    """

    height, width = image.shape[:2]
    work_h, work_w, overlap, starts_y, starts_x = _grid(height, width, tile_h, tile_w, overlap)
    working = _pad(image, work_h, work_w)
    holes = _holes(mask, work_h, work_w)
    result = working.copy()
    flat = np.flatnonzero(holes)
    if flat.size == 0:
        return result[:height, :width]
    channels = working.shape[2]
    total = np.zeros((flat.size, channels), dtype=np.float32)
    weights = np.zeros(flat.size, dtype=np.float32)
    window = _rect_window(tile_h, tile_w, overlap)
    for y in starts_y:
        for x in starts_x:
            tile_mask = holes[y : y + tile_h, x : x + tile_w]
            if not tile_mask.any():
                continue
            output = run(working[y : y + tile_h, x : x + tile_w], tile_mask)
            if output.shape[:2] != (tile_h, tile_w):
                output = cv2.resize(output, (tile_w, tile_h), interpolation=cv2.INTER_CUBIC)
            ys, xs = np.nonzero(tile_mask)
            index = np.searchsorted(flat, (ys + y) * work_w + (xs + x))
            weight = window[ys, xs]
            total[index] += output[ys, xs].astype(np.float32) * weight[:, None]
            weights[index] += weight
            if on_tile is not None:
                on_tile()
    filled = np.clip(total / np.maximum(weights, 1e-6)[:, None], 0, 255)
    result.reshape(-1, channels)[flat] = np.rint(filled) if result.dtype == np.uint8 else filled
    return result[:height, :width]


def _rect_window(tile_h: int, tile_w: int, overlap: int) -> np.ndarray:
    def ramp(size: int) -> np.ndarray:
        values = np.ones(size, dtype=np.float32)
        if overlap > 0:
            slope = np.linspace(0, 1, overlap + 1, dtype=np.float32)[1:]
            values[:overlap] = slope
            values[-overlap:] = np.minimum(values[-overlap:], slope[::-1])
        return values

    return np.minimum(ramp(tile_h)[:, None], ramp(tile_w)[None, :])


def masked_tile_count(mask: np.ndarray, tile_h: int, tile_w: int, overlap: int) -> int:
    """How many tiles `masked_tiles` will run. Empty holes are skipped."""

    height, width = mask.shape[:2]
    work_h, work_w, _overlap, starts_y, starts_x = _grid(height, width, tile_h, tile_w, overlap)
    holes = _holes(mask, work_h, work_w)
    return sum(1 for y in starts_y for x in starts_x if holes[y : y + tile_h, x : x + tile_w].any())


# OpenCV float Lab keeps a and b near -128..127. This export's real predictions stay
# inside about ±110. Anything past that is not a color, and cubic resize turns it into dots.
_AB_LIMIT = 110.0
# A collapsed DDColor map sits near 0 except for a blown patch. A real one does not.
_COLLAPSED_MEDIAN = 2.0
# Gray levels at percentiles 0, 5, 25, 50, 75, 95, and 100. They follow a print this
# export actually colors: a dark mass and open highlights. A high-key or flat scan
# mapped onto that shape produces chroma. Left alone, the same scan comes back gray
# with a few pixels in the hundreds.
_TONE_PERCENTILES = (0, 5, 25, 50, 75, 95, 100)
_TONE_LEVELS = (40, 43, 48, 92, 122, 186, 210)


def apply_ab(image: np.ndarray, ab: np.ndarray) -> np.ndarray:
    """Replace chroma with `ab` in float Lab units (about -128..127), as DDColor returns it."""

    rgb = image.astype(np.float32) / 255.0
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    chroma = _clip_ab(ab)
    if chroma.shape[:2] != image.shape[:2]:
        # Cubic overshoots near a sharp edge. Clipping again keeps it inside the limit.
        chroma = _clip_ab(
            cv2.resize(chroma, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_CUBIC)
        )
    lab[..., 1:3] = chroma
    return unit_to_rgb(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB))


def chroma_collapsed(ab: np.ndarray) -> bool:
    """True when a colorizer result is gray, whatever a few extreme pixels are doing."""

    return float(np.median(_ab_magnitude(_clip_ab(ab)))) < _COLLAPSED_MEDIAN


def tame_ab(ab: np.ndarray) -> np.ndarray:
    """Drop the blown patch on a collapsed map. A real prediction is left in place."""

    chroma = _clip_ab(ab)
    if not chroma_collapsed(chroma):
        return chroma
    chroma[_ab_magnitude(chroma) > 8.0] = 0
    return chroma


def _clip_ab(ab: np.ndarray) -> np.ndarray:
    return np.clip(ab.astype(np.float32), -_AB_LIMIT, _AB_LIMIT)


def _ab_magnitude(ab: np.ndarray) -> np.ndarray:
    return np.linalg.norm(ab, axis=2)


def colorizer_tone(image: np.ndarray) -> np.ndarray:
    """Remap gray levels for the colorizer input. The result is still a gray RGB image."""

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    src = [float(np.percentile(gray, percentile)) for percentile in _TONE_PERCENTILES]
    for index in range(1, len(src)):
        if src[index] <= src[index - 1]:
            src[index] = src[index - 1] + 1e-3
    mapped = np.clip(np.interp(gray, src, _TONE_LEVELS), 0, 255).astype(np.float32)
    return np.repeat(mapped[:, :, None], 3, axis=2)


def lab_gray_rgb(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Gray RGB in 0..1, from Lab lightness with a and b cleared. DDColor's input."""

    rgb = image.astype(np.float32) / 255.0
    resized = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
    lightness = cv2.cvtColor(resized, cv2.COLOR_RGB2LAB)[:, :, :1]
    zeros = np.zeros_like(lightness)
    gray_lab = np.concatenate((lightness, zeros, zeros), axis=-1)
    return cv2.cvtColor(gray_lab, cv2.COLOR_LAB2RGB)


def warp_face(image: np.ndarray, landmarks: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    matrix, _inliers = cv2.estimateAffinePartial2D(
        landmarks.astype(np.float32),
        FACE_TEMPLATE,
        method=cv2.LMEDS,
    )
    if matrix is None:
        return None
    aligned = cv2.warpAffine(
        image,
        matrix,
        (512, 512),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    return aligned, matrix


def paste_face(image: np.ndarray, matrix: np.ndarray, restored: np.ndarray) -> np.ndarray:
    inverse = cv2.invertAffineTransform(matrix)
    height, width = image.shape[:2]
    warped = cv2.warpAffine(restored, inverse, (width, height), flags=cv2.INTER_LINEAR)
    soft = cv2.warpAffine(_face_mask(), inverse, (width, height), flags=cv2.INTER_LINEAR)
    alpha = soft[..., None]
    blended = warped.astype(np.float32) * alpha + image.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255)


def as_nchw(image: np.ndarray) -> np.ndarray:
    tensor = image.astype(np.float32) / 255.0
    return np.transpose(tensor, (2, 0, 1))[None]


def from_model(output: np.ndarray) -> np.ndarray:
    tensor = output[0] if output.ndim == 4 else output
    if tensor.ndim != 3:
        raise RuntimeError("model output is not an image")
    if tensor.shape[0] in {1, 2, 3} and tensor.shape[0] < min(tensor.shape[1], tensor.shape[2]):
        tensor = np.transpose(tensor, (1, 2, 0))
    return tensor


def unit_to_rgb(image: np.ndarray) -> np.ndarray:
    """A 0..1 model output to working float RGB. Overshoot is clipped."""

    return np.clip(image * 255.0, 0, 255).astype(np.float32)


def byte_to_rgb(image: np.ndarray) -> np.ndarray:
    """A 0..255 model output to working float RGB."""

    return np.clip(image, 0, 255).astype(np.float32)


def _normalize(total: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.clip(total / np.maximum(weights, 1e-6), 0, 255)


def _face_mask() -> np.ndarray:
    mask = np.zeros((512, 512), dtype=np.float32)
    cv2.ellipse(mask, (256, 266), (188, 236), 0, 0, 360, 1.0, thickness=-1)
    return cv2.GaussianBlur(mask, (51, 51), 0)


def _pad(image: np.ndarray, height: int, width: int) -> np.ndarray:
    pad_y = max(0, height - image.shape[0])
    pad_x = max(0, width - image.shape[1])
    if pad_y == 0 and pad_x == 0:
        return image
    return cv2.copyMakeBorder(image, 0, pad_y, 0, pad_x, cv2.BORDER_REFLECT)


def _grid(
    height: int,
    width: int,
    tile_h: int,
    tile_w: int,
    overlap: int,
) -> tuple[int, int, int, list[int], list[int]]:
    """Padded size, clamped overlap, and tile origins. The runners and counters share it."""

    work_h, work_w = max(height, tile_h), max(width, tile_w)
    overlap = max(0, min(overlap, tile_h // 2, tile_w // 2))
    return (
        work_h,
        work_w,
        overlap,
        _starts(work_h, tile_h, overlap),
        _starts(work_w, tile_w, overlap),
    )


def _holes(mask: np.ndarray, work_h: int, work_w: int) -> np.ndarray:
    height, width = mask.shape[:2]
    holes = np.zeros((work_h, work_w), dtype=np.uint8)
    holes[:height, :width] = mask.astype(bool)
    return holes


def _starts(length: int, tile: int, overlap: int) -> list[int]:
    step = tile - overlap
    if step < 1:
        raise ValueError("overlap must be smaller than the tile")
    starts = list(range(0, length - tile + 1, step))
    last = length - tile
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def _scale(source_shape: tuple[int, ...], output_shape: tuple[int, ...]) -> tuple[int, int]:
    scale_y = output_shape[0] // source_shape[0]
    scale_x = output_shape[1] // source_shape[1]
    if scale_y < 1 or scale_x < 1 or output_shape[0] != source_shape[0] * scale_y:
        raise RuntimeError("model scale is not an integer")
    if output_shape[1] != source_shape[1] * scale_x:
        raise RuntimeError("model scale is not an integer")
    return scale_y, scale_x


def _window(tile: int, overlap: int, scale: int) -> np.ndarray:
    size = tile * scale
    if overlap <= 0:
        return np.ones((size, size, 1), dtype=np.float32)
    fade = overlap * scale
    ramp = np.ones(size, dtype=np.float32)
    slope = np.linspace(0, 1, fade, endpoint=False, dtype=np.float32)
    ramp[:fade] = slope
    ramp[-fade:] = slope[::-1]
    # Keep a little weight on the outer pixels so a lone border tile still divides cleanly.
    ramp = np.maximum(ramp, 1e-3)
    window = np.minimum(ramp[:, None], ramp[None, :])
    return window[:, :, None]
