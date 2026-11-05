import cv2
import numpy as np


def scratch_mask(image: np.ndarray) -> np.ndarray:
    """Thin bright or dark strokes. Filled areas are not holes for the inpainter."""

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    short = min(int(gray.shape[0]), int(gray.shape[1]))
    length = max(9, int(round(short * 0.02)))
    if length % 2 == 0:
        length += 1
    strokes = np.zeros(gray.shape, dtype=np.uint8)
    for size in ((length, 1), (1, length)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, size)
        for kind in (cv2.MORPH_TOPHAT, cv2.MORPH_BLACKHAT):
            response = cv2.morphologyEx(gray, kind, kernel)
            strokes = cv2.bitwise_or(strokes, np.where(response >= 24, 255, 0).astype(np.uint8))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(strokes, connectivity=8)
    thin = np.zeros(gray.shape, dtype=np.uint8)
    max_thickness = max(3, length // 3)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        minor = max(
            1, min(int(stats[label, cv2.CC_STAT_WIDTH]), int(stats[label, cv2.CC_STAT_HEIGHT]))
        )
        if minor <= max_thickness and area >= length:
            thin[labels == label] = 255
    if not thin.any():
        return np.zeros(gray.shape, dtype=bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.dilate(thin, kernel).astype(bool)
