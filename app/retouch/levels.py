"""Deterministic corrections for faded prints, before any neural restoration."""

import cv2
import numpy as np

from app.imaging.io import as_byte_rgb, as_float_rgb


def _sample(image: np.ndarray) -> np.ndarray:
    # Bound statistics work on large scans; corrections run at full resolution.
    height, width = image.shape[:2]
    scale = min(1.0, 1024 / max(height, width))
    if scale == 1.0:
        return image
    return cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def correct_color_cast(image: np.ndarray) -> np.ndarray:
    """Align robust RGB endpoints without also stretching to full contrast.

    Like percentile white balance, assumes the print has neutral dark/light
    content. This is opt-in: a deliberately warm scene may not fit that assumption.
    Match channels to their mean endpoints so neutral scans stay neutral and
    brightness remains near the scan. Cap gain and skip nearly flat channels to
    avoid amplifying scanner noise in blank prints or missing color information.
    Red-faded scans use automatically estimated reference curves instead.
    """
    source = image
    image = as_float_rgb(image)
    sample = _sample(image)
    low, high = np.percentile(sample.reshape(-1, 3), (1, 99), axis=0)
    span = high - low
    if np.min(span) < 12:
        return source.copy()
    faded = _restore_red_fade(image, sample)
    if faded is not None:
        return as_byte_rgb(faded) if source.dtype == np.uint8 else faded
    target_low, target_high = float(np.mean(low)), float(np.mean(high))
    gain = np.clip((target_high - target_low) / span, 0.5, 3.0)
    midpoint = (low + high) / 2
    target_midpoint = (target_low + target_high) / 2
    result = np.clip(
        (image - midpoint.astype(np.float32)) * gain.astype(np.float32) + target_midpoint, 0, 255
    ).astype(np.float32)
    result = _balance_faded_midtones(result, low, high)
    return as_byte_rgb(result) if source.dtype == np.uint8 else result


def _restore_red_fade(image: np.ndarray, sample: np.ndarray) -> np.ndarray | None:
    """Estimate bounded channel curves from spatially distributed quiet patches.

    Red dominance must persist across tones and most patches in a compressed
    scan. Patch medians reject isolated damage; clipping, texture and border
    rejection keep those artifacts out of the reference. Neutrality is still an
    assumption: confidence limits correction when patches disagree.
    """
    height, width = sample.shape[:2]
    if min(height, width) < 32:
        return None
    my, mx = max(1, height // 20), max(1, width // 20)
    interior = sample[my:-my, mx:-mx]
    low, high = np.percentile(interior.reshape(-1, 3), (2, 98), axis=0)
    span = float(np.mean(high - low))
    if span < 12 or span >= 110:
        return None
    patches = []
    textures = []
    for row in np.array_split(interior, 12, axis=0):
        for patch in np.array_split(row, 12, axis=1):
            pixels = patch.reshape(-1, 3)
            valid = pixels[(pixels.min(axis=1) > 3) & (pixels.max(axis=1) < 252)]
            if len(valid) < max(4, len(pixels) * 0.9):
                continue
            patches.append(np.median(valid, axis=0))
            gray = patch.mean(axis=2)
            textures.append(float(np.mean(np.abs(np.diff(gray, axis=0)))
                                  + np.mean(np.abs(np.diff(gray, axis=1)))))
    if len(patches) < 48:
        return None
    refs = np.asarray(patches)
    refs = refs[np.asarray(textures) <= np.percentile(textures, 70)]
    red = refs[:, 0] - refs[:, 1:].mean(axis=1)
    dominance = float(np.median(red))
    if dominance < 20 or np.mean(red > 15) < 0.9:
        return None
    tone = refs.mean(axis=1)
    edges = np.percentile(tone, np.linspace(0, 100, 6))
    anchors = []
    for index in range(5):
        selected = refs[(tone >= edges[index]) & (tone <= edges[index + 1])]
        if len(selected) < 5:
            return None
        anchor = np.median(selected, axis=0)
        if anchor[0] - anchor[1:].mean() < 15:
            return None
        anchors.append(anchor)
    anchors = np.asarray(anchors)
    target = anchors.mean(axis=1)
    differences = np.diff(anchors, axis=0)
    if np.any(differences < 1) or np.ptp(target) < span * 0.3:
        return None
    slopes = np.diff(target)[:, None] / differences
    if np.any((slopes < 0.5) | (slopes > 2)):
        return None
    residual = refs - refs.mean(axis=1, keepdims=True)
    disagreement = float(np.median(np.abs(residual - np.median(residual, axis=0))))
    confidence = float(np.clip((110 - span) / 40, 0, 1)
                       * np.clip((dominance - 20) / 20, 0, 1)
                       * np.clip(1 - disagreement / 12, 0, 1))
    if confidence < 0.25:
        return None
    # Blend toward the original (warm) scan, not an already cyan endpoint
    # correction. Constant offsets outside the references avoid extrapolation
    # gains in deep shadows or highlights. Curves remain monotonic.
    strength = 0.98 * confidence
    result = np.empty_like(image)
    for channel in range(3):
        knots = np.r_[0, anchors[:, channel], 255]
        offsets = np.clip(target - anchors[:, channel], -60, 60)
        offsets = np.r_[offsets[0], offsets, offsets[-1]] * strength
        for start in range(0, image.shape[0], 128):
            rows = slice(start, start + 128)
            pixels = image[rows, :, channel]
            result[rows, :, channel] = np.clip(
                pixels + np.interp(pixels, knots, offsets), 0, 255
            )
    return result


def _balance_faded_midtones(
    image: np.ndarray, low: np.ndarray, high: np.ndarray, strength: float = 0.75
) -> np.ndarray:
    """Conservatively remove residual midtone cast in strongly faded scans.

    Endpoint alignment cannot correct unequal channel fading through the middle
    of the tone curve. Use the same central pixels in every channel, and taper
    the adjustment to zero at the balanced endpoints. Only low-range scans with
    a substantial original cast qualify: ordinary scene colors are not evidence
    of fading. This remains a neutral-scene heuristic, not color reconstruction.
    """
    span = float(np.mean(high - low))
    cast = float(np.ptp((low + high) / 2))
    confidence = float(np.clip((100 - span) / 40, 0, 1) * np.clip((cast - 15) / 20, 0, 1))
    if confidence == 0:
        return image
    sample = _sample(image)
    gray = sample.mean(axis=2)
    sample_tone = (gray - float(low.mean())) / span
    anchors = np.array([0, 0.25, 0.5, 0.75, 1])
    offsets = np.zeros((5, 3), dtype=np.float32)
    for index, anchor in enumerate(anchors[1:-1], 1):
        central = sample[np.abs(sample_tone - anchor) <= 0.125]
        if len(central) < 32:
            continue
        middle = np.median(central, axis=0)
        offsets[index] = np.clip(middle.mean() - middle, -span * 0.08, span * 0.08)
    offsets *= strength * confidence
    result = np.empty_like(image)
    for start in range(0, image.shape[0], 128):
        rows = slice(start, start + 128)
        pixels = image[rows]
        tone = np.clip((pixels.mean(axis=2) - float(low.mean())) / span, 0, 1)
        for channel in range(3):
            adjustment = np.interp(tone, anchors, offsets[:, channel])
            result[rows, :, channel] = np.clip(pixels[:, :, channel] + adjustment, 0, 255)
    return result


def _haze_floor(sample: np.ndarray) -> np.ndarray:
    """Estimate raised shadows only where a broad neighborhood contains detail.

    A large dark-channel window avoids treating individual highlights as haze.
    The range gate leaves smooth bright backgrounds alone; smoothing and a cap
    limit the impact of scene lighting mistaken for uneven fading.
    """
    size = max(3, round(min(sample.shape) / 8) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    dark = cv2.erode(sample, kernel)
    light = cv2.dilate(sample, kernel)
    baseline = float(np.percentile(sample, 0.5))
    detail = np.clip((light - dark - 12) / 36, 0, 1)
    floor = np.clip((dark - baseline) * 0.65, 0, 48) * detail
    return cv2.GaussianBlur(floor, (0, 0), max(1, min(sample.shape) / 16))


def restore_contrast(image: np.ndarray) -> np.ndarray:
    """Expand faded levels with smoothly varying, shared RGB corrections.

    Half-percent tails ignore dust; a little headroom keeps highlight detail.
    Compress broad illumination differences after stretching the levels, lifting
    shaded areas and holding back bright ones without darkening shadows. Reduce
    locally raised shadows from broad haze where neighboring detail supports it,
    then gently open the deepest tones. Correction fades at black/white
    and is capped to retain natural lighting and avoid harsh halos. Nearly flat
    scans are left alone; shared RGB adjustments keep grayscale neutral.
    """
    source = image
    image = as_float_rgb(image)
    gray = cv2.cvtColor(_sample(image), cv2.COLOR_RGB2GRAY)
    low, high = np.percentile(gray, (0.5, 99.5))
    span = float(high - low)
    if span < 12:
        return source.copy()
    target_low, target_high = min(float(low), 8.0), max(float(high), 247.0)
    gain = min((target_high - target_low) / span, 4.0)
    midpoint = (float(low) + float(high)) / 2
    target_midpoint = (target_low + target_high) / 2
    stretched = np.clip((image - midpoint) * gain + target_midpoint, 0, 255)
    # Estimate illumination at bounded resolution; a broad blur ignores grain
    # and small features. Scaling the radius with the image makes this DPI-independent.
    sample = cv2.cvtColor(_sample(stretched), cv2.COLOR_RGB2GRAY).astype(np.float32)
    haze = _haze_floor(sample)
    base = cv2.GaussianBlur(sample, (0, 0), max(1, min(sample.shape) / 8))
    correction = np.clip((127.5 - base) * 0.6, -32, 32)
    # Apply in strips to bound temporary RGB float allocations on large scans.
    height, width = image.shape[:2]
    correction = cv2.resize(correction, (width, height), interpolation=cv2.INTER_LINEAR)
    haze = cv2.resize(haze, (width, height), interpolation=cv2.INTER_LINEAR)
    result = np.empty_like(image)
    for start in range(0, height, 128):
        rows = slice(start, start + 128)
        pixels = stretched[rows].astype(np.float32)
        # Fade using RGB extrema so even saturated colors remain in gamut with
        # a shared additive adjustment (preserving channel differences).
        headroom = np.minimum(pixels.min(axis=2), 255 - pixels.max(axis=2)) / 255
        weight = 4 * headroom * (1 - headroom)
        local = correction[rows] * weight
        # Holding back a bright surround must not sink dark subjects within it
        # (faces in a crowd against snow): darkening only applies above shadows.
        tone = np.clip((pixels.mean(axis=2) / 255 - 0.25) / 0.5, 0, 1)
        local = np.where(local < 0, local * tone * tone, local)
        corrected = pixels + local[:, :, None]
        # Remove an additive veil and expand the remaining range toward white.
        # Limit removal by the darkest channel to preserve color and true blacks.
        floor = np.minimum(haze[rows], corrected.min(axis=2) * 0.8)
        corrected = (corrected - floor[:, :, None]) * (255 / (255 - floor))[:, :, None]
        result[rows] = _shadow_toe(np.clip(corrected, 0, 255))
    return as_byte_rgb(result) if source.dtype == np.uint8 else result


def _shadow_toe(image: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """Open up deep shadows that the stretch compressed, keeping black at 0.

    Monotonic for strength <= 1.5 and smoothly joins identity at mid-gray, so
    highlights and midtones are untouched. Applied per channel; the lift is
    small enough near black that neutral tones stay neutral.
    """
    u = np.clip(image / 128, 0, 1)
    return image + strength * image * (1 - u) ** 2
