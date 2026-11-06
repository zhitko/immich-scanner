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
    """Expand faded black/white levels using one shared RGB curve.

    Half-percent tails ignore dust; a little headroom keeps highlight detail.
    Full-range and nearly flat scans are left alone. Limiting the expansion to
    4x avoids turning small paper variations into extreme contrast. A shared
    curve keeps grayscale neutral and does not independently rebalance colors.
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
    return cv2.LUT(image, lut.astype(np.uint8))
