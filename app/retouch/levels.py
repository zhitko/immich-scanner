"""Deterministic corrections for faded prints, before any neural restoration."""

import cv2
import numpy as np


def _sample(image: np.ndarray) -> np.ndarray:
    # Bound statistics work on large scans; the LUT still runs at full resolution.
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
    """
    sample = _sample(image)
    low, high = np.percentile(sample.reshape(-1, 3), (1, 99), axis=0)
    span = high - low
    if np.min(span) < 12:
        return image.copy()
    target_low, target_high = float(np.mean(low)), float(np.mean(high))
    gain = np.clip((target_high - target_low) / span, 0.5, 3.0)
    midpoint = (low + high) / 2
    target_midpoint = (target_low + target_high) / 2
    values = np.arange(256, dtype=np.float32)[:, None]
    lut = np.rint(np.clip((values - midpoint) * gain + target_midpoint, 0, 255))
    return cv2.LUT(image, lut.astype(np.uint8).reshape(256, 1, 3))


def restore_contrast(image: np.ndarray) -> np.ndarray:
    """Expand faded levels with smoothly varying, shared RGB corrections.

    Half-percent tails ignore dust; a little headroom keeps highlight detail.
    Compress broad illumination differences after stretching the levels, lifting
    shaded areas and holding back bright ones. Correction fades at black/white
    and is capped to retain natural lighting and avoid harsh halos. Nearly flat
    scans are left alone; shared RGB adjustments keep grayscale neutral.
    """
    gray = cv2.cvtColor(_sample(image), cv2.COLOR_RGB2GRAY)
    low, high = np.percentile(gray, (0.5, 99.5))
    span = float(high - low)
    if span < 12:
        return image.copy()
    target_low, target_high = min(float(low), 8.0), max(float(high), 247.0)
    gain = min((target_high - target_low) / span, 4.0)
    midpoint = (float(low) + float(high)) / 2
    target_midpoint = (target_low + target_high) / 2
    values = np.arange(256, dtype=np.float32)
    lut = np.rint(np.clip((values - midpoint) * gain + target_midpoint, 0, 255))
    stretched = cv2.LUT(image, lut.astype(np.uint8))
    # Estimate illumination at bounded resolution; a broad blur ignores grain
    # and small features. Scaling the radius with the image makes this DPI-independent.
    sample = cv2.cvtColor(_sample(stretched), cv2.COLOR_RGB2GRAY).astype(np.float32)
    base = cv2.GaussianBlur(sample, (0, 0), max(1, min(sample.shape) / 8))
    correction = np.clip((127.5 - base) * 0.6, -32, 32)
    # Apply in strips to bound temporary RGB float allocations on large scans.
    height, width = image.shape[:2]
    correction = cv2.resize(correction, (width, height), interpolation=cv2.INTER_LINEAR)
    result = np.empty_like(image)
    for start in range(0, height, 128):
        rows = slice(start, start + 128)
        pixels = stretched[rows].astype(np.float32)
        # Fade using RGB extrema so even saturated colors remain in gamut with
        # a shared additive adjustment (preserving channel differences).
        headroom = np.minimum(pixels.min(axis=2), 255 - pixels.max(axis=2)) / 255
        weight = 4 * headroom * (1 - headroom)
        corrected = pixels + (correction[rows] * weight)[:, :, None]
        result[rows] = np.rint(np.clip(corrected, 0, 255)).astype(np.uint8)
    return result
