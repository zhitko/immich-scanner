"""Native-resolution paper filters, operating on float RGB in the 0–255 range."""

import cv2
import numpy as np


def _finish(result: np.ndarray, source: np.ndarray) -> np.ndarray:
    result = np.clip(result, 0, 255)
    if source.dtype == np.uint8:
        return np.rint(result).astype(np.uint8)
    return result.astype(np.float32)


def reduce_paper_mesh(image: np.ndarray) -> np.ndarray:
    """Suppress isolated repeating-pattern peaks without broad smoothing.

    Windowing is used only for peak detection. The actual source retains its
    low frequencies and fractional scan levels; conjugate notches are paired.
    """
    h, w = image.shape[:2]
    if min(h, w) < 64:
        return image.copy()
    gray = cv2.cvtColor(image.astype(np.float32), cv2.COLOR_RGB2GRAY)
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    spectrum = np.fft.fftshift(np.fft.fft2((gray - gray.mean()) * window))
    log = np.log1p(np.abs(spectrum)).astype(np.float32)
    excess = log - cv2.GaussianBlur(log, (0, 0), 9)
    y, x = np.ogrid[:h, :w]
    radius = np.sqrt(((y - h // 2) / h) ** 2 + ((x - w // 2) / w) ** 2)
    peaks = (excess > 2.8) & (radius > .035)
    if not peaks.any():
        return image.copy()
    mask = cv2.dilate(peaks.astype(np.float32), np.ones((5, 5), np.uint8))
    mask = np.maximum(mask, np.roll(np.flip(mask, (0, 1)), (1 - h % 2, 1 - w % 2), (0, 1)))
    mask = np.clip(cv2.GaussianBlur(mask, (0, 0), 2) * 1.4, 0, .97)
    result = np.empty(image.shape, np.float32)
    for channel in range(3):
        ft = np.fft.fftshift(np.fft.fft2(image[..., channel]))
        result[..., channel] = np.fft.ifft2(np.fft.ifftshift(ft * (1 - mask))).real
    return _finish(result, image)


def _paper_spectrum(gray: np.ndarray, window: np.ndarray) -> np.ndarray | None:
    """Estimate texture from quiet, non-clipped patches throughout the crop.

    Rank by broad scene variation, rather than high-frequency energy (which
    would preferentially select patches without the paper relief). Sampling
    the whole crop avoids depending on a portrait's particular background.
    """
    n = window.shape[0]
    patches = []
    for y in np.linspace(0, gray.shape[0] - n, 12, dtype=int):
        for x in np.linspace(0, gray.shape[1] - n, 12, dtype=int):
            tile = gray[y:y + n, x:x + n]
            if np.mean((tile < 5) | (tile > 250)) > .1:
                continue
            broad = cv2.GaussianBlur(tile, (0, 0), 5)
            patches.append((float(np.std(broad)), tile - broad))
    if not patches:
        return None
    patches.sort(key=lambda item: item[0])
    samples = [np.abs(np.fft.fft2(tile * window)) ** 2 for _, tile in patches[:16]]
    noise = np.mean(samples, axis=0)
    return np.fft.ifftshift(
        cv2.GaussianBlur(np.fft.fftshift(noise).astype(np.float32), (0, 0), 1)
    )


def reduce_paper_embossed(image: np.ndarray) -> np.ndarray:
    """Local paper-spectrum subtraction at the reviewed medium strength (1.5).

    Shared luminance gains preserve color. Overlapping Hann windows avoid tile
    seams, with reflected borders and a protected low-frequency band. Temporary
    FFT arrays are tile-sized, even for large scans.
    """
    n = 128
    if min(image.shape[:2]) < n:
        return image.copy()
    rgb = image.astype(np.float32)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    window = np.outer(np.hanning(n), np.hanning(n)).astype(np.float32)
    noise = _paper_spectrum(gray, window)
    if noise is None:
        return image.copy()
    freq = np.fft.fftfreq(n)
    radius = np.sqrt(freq[:, None] ** 2 + freq[None, :] ** 2)
    noise *= np.clip((radius - .025) / .025, 0, 1)
    source = cv2.copyMakeBorder(rgb, n, n, n, n, cv2.BORDER_REFLECT_101)
    h, w = source.shape[:2]
    out = np.zeros_like(source)
    weights = np.zeros((h, w), np.float32)
    for y in range(0, h - n + 1, n // 4):
        for x in range(0, w - n + 1, n // 4):
            tile = source[y:y + n, x:x + n]
            mean = tile.mean(axis=(0, 1))
            ft = np.fft.fft2((tile - mean) * window[..., None], axes=(0, 1))
            lum = ft[..., 0] * .299 + ft[..., 1] * .587 + ft[..., 2] * .114
            power = np.abs(lum) ** 2
            gain = np.maximum(1 - 1.5 * noise / np.maximum(power, 1), .08)
            gain[radius < .025] = 1
            clean = np.fft.ifft2(ft * gain[..., None], axes=(0, 1)).real
            out[y:y + n, x:x + n] += (clean + mean * window[..., None]) * window[..., None]
            weights[y:y + n, x:x + n] += window ** 2
    result = out[n:-n, n:-n] / np.maximum(weights[n:-n, n:-n, None], 1e-8)
    return _finish(result, image)
