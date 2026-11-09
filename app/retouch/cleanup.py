"""Conservative, native-resolution cleanup without model downloads."""

import cv2
import numpy as np

from app.imaging.io import as_byte_rgb


def remove_dust(image: np.ndarray) -> np.ndarray:
    """Repair isolated high-contrast specks in otherwise quiet surroundings.

    A fixed small footprint deliberately leaves larger marks to scratch repair.
    Compact components and a quiet surrounding ring avoid most edges and grain.
    """
    gray = cv2.cvtColor(as_byte_rgb(image), cv2.COLOR_RGB2GRAY)
    background = cv2.medianBlur(gray, 7)
    residual = cv2.absdiff(gray, background)
    candidates = (residual >= 32).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates, 8)
    mask = np.zeros(gray.shape, np.uint8)
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area > 12 or max(w, h) > 5 or max(w, h) > 3 * min(w, h):
            continue
        if x < 3 or y < 3 or x + w + 3 > gray.shape[1] or y + h + 3 > gray.shape[0]:
            continue
        patch = gray[y - 3 : y + h + 3, x - 3 : x + w + 3]
        ring = np.ones(patch.shape, bool)
        ring[2 : h + 4, 2 : w + 4] = False
        if float(np.std(patch[ring])) > 10:
            continue
        mask[y : y + h, x : x + w][labels[y : y + h, x : x + w] == label] = 255
    if not mask.any():
        return image.copy()
    if image.dtype == np.uint8:
        return cv2.inpaint(image, mask, 2, cv2.INPAINT_TELEA)
    return np.clip(
        np.stack(
            [cv2.inpaint(image[..., channel], mask, 2, cv2.INPAINT_TELEA) for channel in range(3)],
            axis=2,
        ),
        0,
        255,
    )


def gentle_denoise(image: np.ndarray) -> np.ndarray:
    """Small-window non-local means at source size, blended to retain texture."""
    proxy = as_byte_rgb(image)
    bgr = cv2.cvtColor(proxy, cv2.COLOR_RGB2BGR)
    clean = cv2.cvtColor(cv2.fastNlMeansDenoisingColored(bgr, None, 3, 3, 7, 15), cv2.COLOR_BGR2RGB)
    if image.dtype == np.uint8:
        return cv2.addWeighted(image, 0.25, clean, 0.75, 0)
    # NLM requires bytes. Apply its estimated noise residual to the float
    # source so quantization of the analysis copy cannot erase scan precision.
    return np.clip(image + 0.75 * (clean.astype(np.float32) - proxy), 0, 255)


def deblur(image: np.ndarray) -> np.ndarray:
    """Regularized, mild Gaussian-defocus deconvolution on luminance.

    Five Richardson–Lucy iterations with bounded, blended detail limit ringing
    and noise amplification. This targets mild softness, not large motion blur.
    Process overlapping strips to bound temporary memory on large scans.
    """
    result = np.empty_like(image)
    for start in range(0, image.shape[0], 256):
        end = min(start + 256, image.shape[0])
        top, bottom = max(0, start - 32), min(image.shape[0], end + 32)
        rgb = image[top:bottom].astype(np.float32) / 255
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        observed = lab[..., 0] / 100
        estimate = np.maximum(observed, 1e-4)
        for _ in range(5):
            blurred = cv2.GaussianBlur(estimate, (7, 7), 0.8)
            ratio = observed / np.maximum(blurred, 1e-4)
            estimate *= cv2.GaussianBlur(ratio, (7, 7), 0.8)
        detail = np.clip(estimate - observed, -0.06, 0.06)
        lab[..., 0] = np.clip(observed + 0.5 * detail, 0, 1) * 100
        restored = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        pixels = np.clip(restored[start - top : end - top], 0, 1) * 255
        result[start:end] = np.rint(pixels) if image.dtype == np.uint8 else pixels
    return result
