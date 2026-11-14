"""Opt-in border damage repair and texture-preserving edge tone correction."""

import cv2
import numpy as np

from app.imaging.io import as_byte_rgb, as_float_rgb


def _edge_views(image: np.ndarray) -> tuple[np.ndarray, ...]:
    """Rows follow the edge; columns point inward, in every orientation."""
    return image, image[:, ::-1], image.swapaxes(0, 1), image[::-1].swapaxes(0, 1)


def _sample(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    scale = min(1.0, 1024 / max(h, w))
    if scale == 1:
        return as_float_rgb(image)
    return cv2.resize(
        as_float_rgb(image), (max(1, round(w * scale)), max(1, round(h * scale))),
        interpolation=cv2.INTER_AREA,
    )


def corner_context(image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Mirror clean context and holes together so LaMa fills inside a tile.

    Without the mirrored holes, padding presents a copy of the damage as valid
    context. Without padding, border-only repairs can produce dark streaks.
    """
    # At scan resolution a tile may contain only damage and a sliver of sky.
    # Give the model a wider scene view; only masked pixels use its output.
    scale = min(1.0, 1536 / max(image.shape[:2]))
    if scale < 1:
        size = (round(image.shape[1] * scale), round(image.shape[0] * scale))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0
    pad = max(32, (512 - min(image.shape[:2]) + 1) // 2)
    return (
        cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_REFLECT),
        cv2.copyMakeBorder(mask.astype(np.uint8), pad, pad, pad, pad,
                           cv2.BORDER_REFLECT).astype(bool),
        pad,
    )


def blend_corner_fill(image: np.ndarray, filled: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Restore source dimensions and use model pixels only inside the repair margin."""
    h, w = image.shape[:2]
    filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_LINEAR)
    radius = max(2, round(max(h, w) / 1536 * 2))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    expanded = cv2.dilate(mask.astype(np.uint8), kernel).astype(np.float32)
    soft = cv2.GaussianBlur(expanded, (0, 0), max(1, radius / 2))
    soft[mask] = 1
    return image * (1 - soft[..., None]) + filled * soft[..., None]


def _border_mask(sample: np.ndarray) -> np.ndarray:
    """Include thin scanner frames and bright strips, with sustained edge support."""
    short = min(sample.shape[:2])
    depth = max(2, round(short * 0.03))
    reference = max(depth + 2, round(short * 0.06))
    frame_depth = max(1, round(short * 0.012))
    result = np.zeros(sample.shape[:2], np.uint8)
    for view, target in zip(_edge_views(sample), _edge_views(result), strict=True):
        # A scanner frame is a thin, straight, dark run along most of an edge.
        baseline = np.median(view[:, depth:reference], axis=1)
        dark = np.mean(baseline[:, None] - view[:, :frame_depth], axis=2)
        columns = np.mean(dark > 22, axis=0) > 0.65
        frame = 0
        for x in range(frame_depth):
            if columns[x]:
                frame = x + 1
        if frame:
            target[:, :frame + 1] = 1
            dark_rows = np.mean(baseline[:, None] - view[:, :depth], axis=2) > 22
            for y, row in enumerate(dark_rows):
                hits = np.flatnonzero(row)
                if len(hits) and hits[0] <= frame and hits[-1] < depth - 1:
                    target[y, :int(hits[-1]) + 2] = 1
        target |= _bright_edge_strip(view, short, frame)
    return result


def _bright_edge_strip(view: np.ndarray, short: int, frame: int) -> np.ndarray:
    """Follow a confirmed pale strip to its local return to interior tones.

    Wider reference bands avoid estimating the scene from damaged paper. Each
    row must start at the outer edge and stop at the first tonal recovery;
    disconnected highlights cannot extend the repair into the scene.
    """
    result = np.zeros(view.shape[:2], np.uint8)
    reach = max(4, round(short * 0.12))
    smooth = cv2.GaussianBlur(view[:, :reach], (1, 0), sigmaX=0,
                              sigmaY=max(1, short * 0.012))
    entry = max(frame + 2, round(short * 0.012))
    for fraction in (0.03, 0.05, 0.08):
        depth = max(3, round(short * fraction))
        stop = min(reach, max(depth + 2, round(depth * 1.5)))
        base = np.median(smooth[:, depth:stop], axis=1)
        excess = np.min(smooth[:, :depth] - base[:, None], axis=2)
        core = (excess > 14) & (smooth[:, :depth].mean(axis=2) > 165)
        weak = excess > 5
        strip = np.zeros_like(core, np.uint8)
        for y in range(len(view)):
            seeds = np.flatnonzero(core[y, :entry])
            if not len(seeds):
                continue
            start = int(seeds[0])
            gaps = np.flatnonzero(~weak[y, start:])
            if not len(gaps):
                continue  # Damage or scenery continues beyond the supported width.
            end = start + int(gaps[0])
            if end >= 2:
                strip[y, :end + 1] = 1
        count, labels, stats, _ = cv2.connectedComponentsWithStats(strip)
        for label in range(1, count):
            width = stats[label, cv2.CC_STAT_WIDTH]
            length = stats[label, cv2.CC_STAT_HEIGHT]
            # A snow wedge merely crossing an edge is not a sustained strip.
            if length >= max(short * 0.10, width * 4):
                result[:, :depth][labels == label] = 1
    # A pale scanner strip may raise channels unequally on a color-faded
    # print. Require a long continuous strip for this weaker, narrow test.
    depth = max(3, round(short * 0.03))
    base = np.median(smooth[:, depth:round(depth * 1.5)], axis=1)
    delta = smooth[:, :depth] - base[:, None]
    core = ((delta.mean(axis=2) > 6) & (delta.max(axis=2) > 12)
            & (delta.min(axis=2) > -4) & (smooth[:, :depth].mean(axis=2) > 155))
    weak = ((delta.mean(axis=2) > 3) & (delta.max(axis=2) > 6)
            & (delta.min(axis=2) > -6))
    strip = np.zeros_like(core, np.uint8)
    for y in range(len(view)):
        seeds = np.flatnonzero(core[y, :entry])
        if not len(seeds):
            continue
        start = int(seeds[0])
        gaps = np.flatnonzero(~weak[y, start:])
        if len(gaps):
            strip[y, :start + int(gaps[0]) + 1] = 1
    count, labels, stats, _ = cv2.connectedComponentsWithStats(strip)
    if np.mean(strip.any(axis=1)) >= 0.25:
        accepted = np.zeros_like(strip)
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_HEIGHT] >= len(view) * 0.06:
                accepted[labels == label] = 1
        # The same physical strip can lose contrast over bright sky. Bridge
        # bounded gaps between confirmed segments using their measured widths,
        # never extrapolate a strip into an unsupported part of the edge.
        rows = np.flatnonzero(accepted.any(axis=1))
        widths = accepted.sum(axis=1)
        for left, right in zip(rows[:-1], rows[1:], strict=True):
            if 1 < right - left <= len(view) * 0.25:
                for y in range(left + 1, right):
                    width = round(float(np.interp(y, [left, right], widths[[left, right]])))
                    accepted[y, :width] = 1
        result[:, :depth] |= accepted
    return result


def normalize_edge_fade(image: np.ndarray) -> np.ndarray:
    """Subtract a bounded, smooth edge veil while retaining local texture.

    Fit RGB shadow/midtone profiles to a linear scene trend plus a decaying
    edge term. A linear sky gradient alone is insufficient evidence. The
    correction is additive, opt-in, and fades to zero in the image interior.
    """
    if min(image.shape[:2]) < 64:
        return image.copy()
    sample = _sample(image)
    short = min(sample.shape[:2])
    if short < 32:
        return image.copy()
    depth = max(12, round(short * 0.25))
    skip = max(2, round(short * 0.015))
    step = max(8, round(short * 0.08))
    field = np.zeros_like(sample)
    weight = np.zeros(sample.shape[:2], np.float32)
    for view, output, weights in zip(
        _edge_views(sample), _edge_views(field), _edge_views(weight), strict=True
    ):
        distance = np.arange(depth, dtype=np.float32) / short
        x = distance[skip:]
        linear = np.column_stack([np.ones_like(x), x])
        for y in range(0, len(view), step):
            lo, hi = max(0, y - step), min(len(view), y + 2 * step)
            profiles = np.percentile(view[lo:hi, :depth], [20, 50], axis=0).mean(axis=0)
            observed = profiles[skip:]
            trend = linear @ np.linalg.lstsq(linear, observed, rcond=None)[0]
            linear_error = float(np.mean((observed - trend) ** 2))
            best = None
            for decay in (0.025, 0.05, 0.08):
                design = np.column_stack([linear, np.exp(-x / decay)])
                coefficients = np.linalg.lstsq(design, observed, rcond=None)[0]
                amplitude = coefficients[2]
                error = float(np.mean((observed - design @ coefficients) ** 2))
                if (amplitude.min() < -3 or np.sum(amplitude > 6) < 2
                        or amplitude.max() > 65 or linear_error < 1
                        or error > linear_error * 0.65 or error > 16):
                    continue
                if best is None or error < best[0]:
                    best = error, decay, np.clip(amplitude, 0, 40)
            if best is None:
                continue
            _, decay, amplitude = best
            taper = np.exp(-distance / decay) * (1 - distance / distance[-1]) ** 2
            correction = taper[:, None] * amplitude[None] * 0.85
            rows = np.arange(lo, hi)
            ramp = np.maximum(0, 1 - np.abs(rows - (y + step / 2)) / (1.5 * step))
            output[lo:hi, :depth] += ramp[:, None, None] * correction[None]
            weights[lo:hi, :depth] += ramp[:, None]
    field /= np.maximum(weight[..., None], 1)
    field = cv2.GaussianBlur(field, (0, 0), max(1, short * 0.012))
    # Strongly red-faded prints can also have a broad loss of that cast along
    # one edge. Require both G and B to rise relative to R in most independent
    # edge segments. Shared scene brightness (snow/sky) cancels in these
    # differences. This is still a faded-print assumption, bounded below.
    field = np.maximum(field, _red_edge_veil(sample))
    field = np.maximum(field, _narrow_edge_veil(sample))
    h, w = image.shape[:2]
    correction = cv2.resize(field, (w, h), interpolation=cv2.INTER_LINEAR)
    result = np.clip(as_float_rgb(image) - correction, 0, 255)
    return as_byte_rgb(result) if image.dtype == np.uint8 else result


def _narrow_edge_veil(sample: np.ndarray) -> np.ndarray:
    """Normalize faint strips too subtle for destructive inpainting.

    Use a near-edge exponential plus a linear scene trend. Require the same
    positive veil across at least a quarter of the edge; isolated bright scene
    objects and linear sky gradients do not qualify.
    """
    short = min(sample.shape[:2])
    depth = max(16, round(short * 0.08))
    skip = max(1, round(short * 0.004))
    step = max(8, round(short * 0.08))
    distance = np.arange(depth, dtype=np.float32) / short
    x = distance[skip:]
    linear = np.column_stack([np.ones_like(x), x])
    field = np.zeros_like(sample)
    for view, target in zip(_edge_views(sample), _edge_views(field), strict=True):
        estimates = []
        for y in range(0, len(view), step):
            lo, hi = max(0, y - step), min(len(view), y + 2 * step)
            observed = np.median(view[lo:hi, skip:depth], axis=0)
            error0 = np.mean((observed - linear @ np.linalg.lstsq(
                linear, observed, rcond=None)[0]) ** 2)
            best = None
            for decay in (0.006, 0.012, 0.02):
                design = np.column_stack([linear, np.exp(-x / decay)])
                coefficients = np.linalg.lstsq(design, observed, rcond=None)[0]
                amplitude = coefficients[2]
                error = float(np.mean((observed - design @ coefficients) ** 2))
                if (amplitude.min() < 2 or amplitude.max() > 60
                        or error0 < 0.5 or error > error0 * 0.5 or error > 5):
                    continue
                if best is None or error < best[0]:
                    best = error, decay, np.clip(amplitude, 0, 30)
            estimates.append((y, lo, hi, best))
        if sum(item[3] is not None for item in estimates) < len(estimates) * 0.25:
            continue
        weights = np.zeros(view.shape[:2], np.float32)
        correction = np.zeros_like(view)
        for y, lo, hi, best in estimates:
            rows = np.arange(lo, hi)
            ramp = np.maximum(0, 1 - np.abs(rows - (y + step / 2)) / (1.5 * step))
            weights[lo:hi, :depth] += ramp[:, None]
            if best is None:
                continue
            _, decay, amplitude = best
            taper = np.exp(-distance / decay) * (1 - distance / distance[-1]) ** 2
            correction[lo:hi, :depth] += ramp[:, None, None] * taper[None, :, None] * amplitude
        target[:] = np.maximum(target, correction / np.maximum(weights[..., None], 1))
    return cv2.GaussianBlur(field, (0, 0), max(1, short * 0.008))


def _red_edge_veil(sample: np.ndarray) -> np.ndarray:
    field = np.zeros_like(sample)
    short = min(sample.shape[:2])
    margin = max(1, round(short * 0.05))
    interior = sample[margin:-margin, margin:-margin]
    low, high = np.percentile(interior.reshape(-1, 3), [2, 98], axis=0)
    red = interior[..., 0] - interior[..., 1:].mean(axis=2)
    if (np.mean(high - low) > 110 or np.median(red) < 20
            or np.mean(red > 15) < 0.8):
        return field
    depth = max(12, round(short * 0.30))
    near = slice(max(1, round(short * 0.02)), max(2, round(short * 0.06)))
    far = slice(round(short * 0.22), depth)
    for view, target in zip(_edge_views(sample), _edge_views(field), strict=True):
        chroma = view[:, :depth, 1:] - view[:, :depth, :1]
        profiles = np.array([np.median(row, axis=0) for row in np.array_split(chroma, 10)])
        baseline = np.median(profiles[:, far], axis=1)
        shifts = np.median(profiles[:, near], axis=1) - baseline
        supported = np.all(shifts > 6, axis=1)
        if np.mean(supported) < 0.8:
            continue
        profile = np.median(profiles - baseline[:, None], axis=0)
        profile = cv2.GaussianBlur(profile[None].astype(np.float32), (0, 1),
                                   sigmaX=max(1, short * 0.025))[0]
        # Suppress texture in the estimate; a veil must decay toward the interior.
        profile = np.maximum.accumulate(np.maximum(profile, 0)[::-1], axis=0)[::-1]
        x = np.arange(depth, dtype=np.float32) / (depth - 1)
        taper = 1 - x * x * (3 - 2 * x)
        correction = np.clip(profile, 0, 28) * taper[:, None] * 0.9
        target[:, :depth, 1:] = np.maximum(target[:, :depth, 1:], correction[None])
    return field


def light_corner_mask(image: np.ndarray) -> np.ndarray:
    """Find locally brighter paper damage, leaving broad highlights alone.

    Work at a bounded resolution so the geometry is independent of scan DPI.
    Corner chips need a strong bright core and a small footprint. Sustained
    narrow bright strips and dark scanner frames are also included. Broad
    fading is handled by a separate tonal correction, never by this fill mask.
    """
    height, width = image.shape[:2]
    empty = np.zeros((height, width), dtype=bool)
    if min(height, width) < 32:
        return empty
    scale = min(1.0, 1024 / max(height, width))
    working = as_byte_rgb(image)
    if scale < 1:
        working = cv2.resize(
            working, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA
        )
    h, w = working.shape[:2]
    short = min(h, w)
    if short < 16:
        return empty
    extent = max(8, round(short * 0.12))
    radius = max(3, round(short * 0.04))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    smooth = cv2.GaussianBlur(working.astype(np.float32), (3, 3), 0.6)
    # Require a rise in every channel, not just a saturated colored object.
    background = cv2.morphologyEx(smooth, cv2.MORPH_OPEN, kernel)
    excess = np.min(smooth - background, axis=2)
    light = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY)
    core = (excess >= 18) & (light >= 170)
    mask = _border_mask(working.astype(np.float32))
    edge = max(1, round(short * 0.006))
    reach = max(extent + 1, round(short * 0.4))
    for flip_y, flip_x in ((False, False), (False, True), (True, False), (True, True)):
        ys = slice(None, None, -1) if flip_y else slice(None)
        xs = slice(None, None, -1) if flip_x else slice(None)
        corner_light = light[ys, xs][:extent, :extent]
        threshold = max(150, float(np.percentile(corner_light, 90)) - 8)
        corner = (
            (excess[ys, xs][:reach, :reach] >= 6)
            & (light[ys, xs][:reach, :reach] >= threshold)
        ).astype(np.uint8)
        seeds = core[ys, xs][:reach, :reach]
        target = mask[ys, xs][:reach, :reach]
        count, labels, stats, _ = cv2.connectedComponentsWithStats(corner, connectivity=8)
        for label in range(1, count):
            x, y, cw, ch, area = stats[label]
            # A narrow worn edge can continue beyond the corner, but never into
            # the scene. Reject components clipped by the search window.
            compact = x + cw < extent and y + ch < extent
            strip = x + cw < short * 0.04 or y + ch < short * 0.04
            if not (compact or strip) or x + cw >= reach or y + ch >= reach:
                continue
            if min(x, y) >= edge or max(x, y) >= extent or area > extent * extent * 0.35:
                continue
            component = labels == label
            if area < 2 or not np.any(seeds & component):
                continue
            if not (component[:edge].any() or component[:, :edge].any()):
                continue
            target[component] = 1
    if not mask.any():
        return empty
    # Include the pale transition around damaged paper, so it cannot become
    # the model's reference color. Scale this margin with the scan dimensions.
    radius = max(1, round(short * 0.005))
    margin = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    mask = cv2.dilate(mask, margin)
    return cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
