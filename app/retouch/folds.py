import cv2
import numpy as np

from app.retouch.scratch import Fold

# How far, in band radii, a fold's shadow reaches past the filled cracks.
_SPREAD = 2
# The step between the sides eases out over this many spreads on each side.
_STEP_REACH = 2
_GAIN_LOW = 0.75
_GAIN_HIGH = 1.3
# Blocks on each side whose median joins one block's, so detail that crosses the fold
# in a few places is outvoted by the shadow, which runs the whole length.
_NEIGHBORS = 2


def even_fold_shading(image: np.ndarray, folds: list[Fold], mask: np.ndarray) -> np.ndarray:
    """Lift the shadow, or tone down the sheen, that a bent print leaves along a fold.

    The paper on each side of a fold sits at an angle to the scanner lamp and comes
    back as a darker or lighter strip that starts at the crack. Each side is brought to
    its own level further out, and the step between the sides eases out, so a real
    difference between them stays. `mask` is the filled area. Each strip is measured
    from its edge, where the shadow starts. The filled pixels take a gain that runs from
    one side's to the other's, the way the fill runs from one side's picture to the other's.
    """

    result = image
    for fold in folds:
        if fold.along.size < 2:
            continue
        result = _even(result, fold, mask)
    return result


def _even(image: np.ndarray, fold: Fold, mask: np.ndarray) -> np.ndarray:
    data = image if fold.axis == "h" else np.ascontiguousarray(image.transpose(1, 0, 2))
    holes = mask if fold.axis == "h" else mask.T
    cross_size = data.shape[0]
    spread = max(8, int(round(fold.radius * _SPREAD)))
    margin = max(4, fold.radius // 3)
    block = max(16, fold.radius)
    along = fold.along
    top, bottom = _edges(_smooth(fold.centers, block), along, holes, fold.radius)
    reach = spread * _STEP_REACH
    steps = np.arange(1, reach + 1)
    ends = _along_weight(along.size, block)[None, :]
    fade = np.clip((spread - margin - steps[:spread]) / max(1, margin), 0.0, 1.0)[:, None] * ends
    # The step between the two sides eases out over `reach`, so it reads as a gradient.
    ease = np.clip(1.0 - steps / reach, 0.0, 1.0)[:, None] * ends

    result = np.array(data, copy=True)
    sides = []
    for rows in (top[None, :] - steps[:, None], bottom[None, :] + steps[:, None]):
        valid = (rows >= 0) & (rows < cross_size)
        safe = np.clip(rows, 0, cross_size - 1)
        strip = data[safe, along[None, :]].astype(np.float32)
        counted = valid & ~holes[safe, along[None, :]]
        # One gain for all channels. The lamp's shadow is not colored, and a gain per
        # channel follows whichever color the picture has there and tints it.
        level = strip.mean(axis=2)[:spread]
        level[~counted[:spread]] = np.nan
        gain = np.ones(strip.shape[:2], dtype=np.float32)
        gain[:spread] = 1.0 + (_gain(level, margin, block) - 1.0) * fade
        near = _pooled(level[:margin] / gain[:margin], block)
        sides.append((safe, valid, strip, gain, near))
    middle = np.sqrt(sides[0][4] * sides[1][4])
    for _safe, _valid, _strip, gain, near in sides:
        step = np.clip(middle / np.maximum(near, 1.0), _GAIN_LOW, _GAIN_HIGH)
        gain /= step[None, :] ** ease
    for safe, valid, strip, gain, _near in sides:
        corrected = np.clip(np.rint(strip / gain[:, :, None]), 0, 255).astype(np.uint8)
        result[safe[valid], np.broadcast_to(along[None, :], safe.shape)[valid]] = corrected[valid]
    _even_inside(result, data, along, top, bottom, sides[0][3][0], sides[1][3][0])
    return result if fold.axis == "h" else np.ascontiguousarray(result.transpose(1, 0, 2))


def _even_inside(
    result: np.ndarray,
    data: np.ndarray,
    along: np.ndarray,
    top: np.ndarray,
    bottom: np.ndarray,
    gain_top: np.ndarray,
    gain_bottom: np.ndarray,
) -> None:
    span = int((bottom - top).max()) + 1
    if span < 1:
        return
    offsets = np.arange(span)[:, None]
    rows = top[None, :] + offsets
    inside = (rows <= bottom[None, :]) & (rows >= 0) & (rows < data.shape[0])
    t = offsets / np.maximum(bottom - top, 1)[None, :]
    gain = gain_top[None, :] * (1.0 - t) + gain_bottom[None, :] * t
    safe = np.clip(rows, 0, data.shape[0] - 1)
    cols = np.broadcast_to(along[None, :], rows.shape)
    values = data[safe, cols].astype(np.float32) / gain[:, :, None]
    result[safe[inside], cols[inside]] = np.clip(np.rint(values[inside]), 0, 255).astype(np.uint8)


def _edges(
    centers: np.ndarray, along: np.ndarray, holes: np.ndarray, radius: int
) -> tuple[np.ndarray, np.ndarray]:
    """First and last filled row near each centre. Columns with none use the centre."""

    offsets = np.arange(-radius, radius + 1)
    rows = np.rint(centers[None, :] + offsets[:, None]).astype(np.int64)
    inside = (rows >= 0) & (rows < holes.shape[0])
    hit = holes[np.clip(rows, 0, holes.shape[0] - 1), along[None, :]] & inside
    found = hit.any(axis=0)
    first = np.argmax(hit, axis=0) - radius
    last = hit.shape[0] - 1 - np.argmax(hit[::-1], axis=0) - radius
    top = np.where(found, centers + first, centers)
    bottom = np.where(found, centers + last, centers)
    window = max(3, radius // 4)
    return (
        np.rint(_smooth(top, window)).astype(np.int64),
        np.rint(_smooth(bottom, window)).astype(np.int64),
    )


def _gain(level: np.ndarray, margin: int, block: int) -> np.ndarray:
    """Brightness near the crack over the same side's level further out, as a smooth map."""

    with np.errstate(all="ignore"):
        far = np.nanmedian(level[-margin:], axis=0)
    ratio = level / np.maximum(far, 1.0)[None, :]
    ratio[~np.isfinite(ratio)] = np.nan

    length = level.shape[1]
    starts = list(range(0, length, block))
    per_block = np.full((level.shape[0], len(starts)), np.nan, dtype=np.float32)
    with np.errstate(all="ignore"):
        for index, start in enumerate(starts):
            chunk = ratio[:, start : start + block]
            if np.isfinite(chunk).any():
                per_block[:, index] = np.nanmedian(chunk, axis=1)
        pooled = np.empty_like(per_block)
        for index in range(len(starts)):
            lo, hi = max(0, index - _NEIGHBORS), min(len(starts), index + _NEIGHBORS + 1)
            pooled[:, index] = np.nanmedian(per_block[:, lo:hi], axis=1)
    pooled = np.nan_to_num(pooled, nan=1.0)
    pooled = cv2.GaussianBlur(pooled, (1, 0), sigmaX=0.1, sigmaY=1.5)
    pooled = np.clip(pooled, _GAIN_LOW, _GAIN_HIGH)

    middles = np.array([min(length - 1, start + block / 2) for start in starts])
    positions = np.arange(length)
    gain = np.empty(level.shape, dtype=np.float32)
    for row in range(level.shape[0]):
        gain[row] = np.interp(positions, middles, pooled[row])
    return gain


def _pooled(level: np.ndarray, block: int) -> np.ndarray:
    """One robust level per position along the fold, from the rows in `level`."""

    length = level.shape[1]
    starts = list(range(0, length, block))
    with np.errstate(all="ignore"):
        per_block = np.array(
            [np.nanmedian(level[:, start : start + block]) for start in starts], dtype=np.float32
        )
        pooled = np.array(
            [
                np.nanmedian(per_block[max(0, i - _NEIGHBORS) : i + _NEIGHBORS + 1])
                for i in range(len(starts))
            ],
            dtype=np.float32,
        )
    pooled = np.nan_to_num(pooled, nan=1.0)
    middles = np.array([min(length - 1, start + block / 2) for start in starts])
    return np.interp(np.arange(length), middles, pooled).astype(np.float32)


def _along_weight(length: int, block: int) -> np.ndarray:
    distance = np.minimum(np.arange(length), np.arange(length)[::-1]).astype(np.float32)
    return np.clip(distance / max(1, block), 0.0, 1.0)


def _smooth(centers: np.ndarray, size: int) -> np.ndarray:
    if centers.size < 3:
        return centers.astype(np.float64)
    width = min(centers.size, size | 1)
    padded = np.pad(centers.astype(np.float64), width // 2, mode="edge")
    return np.convolve(padded, np.ones(width) / width, mode="valid")[: centers.size]
