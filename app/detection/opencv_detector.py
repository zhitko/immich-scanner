from dataclasses import dataclass

import cv2
import numpy as np

from app.detection.base import DetectedRegion


@dataclass(frozen=True)
class DetectorConfig:
    max_edge: int = 1400
    min_area_ratio: float = 0.004
    min_side_ratio: float = 0.02
    border_fraction: float = 0.012
    min_tolerance: int = 12
    max_tolerance: int = 36


class OpenCvPhotoDetector:
    """Separate prints from a flatbed lid by flood-filling the background.

    The lid is usually white or black. Seeds are taken from border pixels close
    to the border median, so both lids work, and a print whose interior matches
    the lid is still kept when its edge stops the flood. The close kernel stays
    smaller than a typical 5 mm gap so neighbouring prints are not merged.
    """

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self._config = config or DetectorConfig()

    def detect(self, image: np.ndarray) -> list[DetectedRegion]:
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("detector expected an HxWx3 RGB image")
        height, width = image.shape[:2]
        if min(height, width) < 32:
            return []
        small, scale_x, scale_y = _downscale(image, self._config.max_edge)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        foreground = self._foreground_mask(gray)
        contours, _hierarchy = cv2.findContours(
            foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        small_h, small_w = gray.shape
        min_area = self._config.min_area_ratio * small_h * small_w
        min_side = self._config.min_side_ratio * min(small_h, small_w)
        found: list[DetectedRegion] = []
        for contour in contours:
            if cv2.contourArea(contour) < min_area:
                continue
            (center_x, center_y), (rect_w, rect_h), angle = cv2.minAreaRect(contour)
            if rect_w < min_side or rect_h < min_side:
                continue
            if rect_w * rect_h > 0.98 * small_w * small_h:
                continue
            found.append(
                DetectedRegion(
                    center_x=float(center_x) * scale_x,
                    center_y=float(center_y) * scale_y,
                    width=float(rect_w) * scale_x,
                    height=float(rect_h) * scale_y,
                    angle_deg=float(angle),
                )
            )
        return sort_reading_order(found)

    def _foreground_mask(self, gray: np.ndarray) -> np.ndarray:
        height, width = gray.shape
        band = max(2, int(round(min(height, width) * self._config.border_fraction)))
        border = np.concatenate(
            [
                gray[:band, :].ravel(),
                gray[-band:, :].ravel(),
                gray[:, :band].ravel(),
                gray[:, -band:].ravel(),
            ]
        )
        median = float(np.median(border))
        tolerance = int(
            max(
                self._config.min_tolerance,
                min(self._config.max_tolerance, float(border.std()) * 2 + 8),
            )
        )
        mask = np.zeros((height + 2, width + 2), np.uint8)
        flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
        source = gray.copy()
        for x, y in _border_seeds(gray, median, tolerance):
            if mask[y + 1, x + 1] != 0:
                continue
            cv2.floodFill(
                source,
                mask,
                (x, y),
                0,
                loDiff=tolerance,
                upDiff=tolerance,
                flags=flags,
            )
        background = mask[1:-1, 1:-1]
        foreground = np.where(background == 0, 255, 0).astype(np.uint8)
        kernel = _odd_size(min(height, width) * 0.008)
        closed = cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)),
        )
        open_size = _odd_size(max(3, kernel // 3))
        return cv2.morphologyEx(
            closed,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size)),
        )


def sort_reading_order(regions: list[DetectedRegion]) -> list[DetectedRegion]:
    if not regions:
        return []
    heights = sorted(region.height for region in regions)
    row_tolerance = max(20.0, heights[len(heights) // 2] * 0.45)
    rows: list[list[DetectedRegion]] = []
    for region in sorted(regions, key=lambda item: item.center_y):
        placed = False
        for row in rows:
            average_y = sum(item.center_y for item in row) / len(row)
            if abs(region.center_y - average_y) <= row_tolerance:
                row.append(region)
                placed = True
                break
        if not placed:
            rows.append([region])
    ordered: list[DetectedRegion] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda item: item.center_x))
    return ordered


def _downscale(image: np.ndarray, max_edge: int) -> tuple[np.ndarray, float, float]:
    height, width = image.shape[:2]
    scale = min(1.0, max_edge / max(height, width))
    small_w = max(1, int(round(width * scale)))
    small_h = max(1, int(round(height * scale)))
    if small_w == width and small_h == height:
        return image, 1.0, 1.0
    small = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_AREA)
    return small, width / small_w, height / small_h


def _border_seeds(gray: np.ndarray, median: float, tolerance: int) -> list[tuple[int, int]]:
    height, width = gray.shape
    step = max(4, min(height, width) // 80)
    seeds: list[tuple[int, int]] = []

    def consider(x: int, y: int) -> None:
        if abs(int(gray[y, x]) - median) <= tolerance + 2:
            seeds.append((x, y))

    for x in range(0, width, step):
        consider(x, 0)
        consider(x, height - 1)
    for y in range(0, height, step):
        consider(0, y)
        consider(width - 1, y)
    if seeds:
        return seeds
    return [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]


def _odd_size(value: float) -> int:
    size = max(3, int(round(value)))
    if size % 2 == 0:
        size += 1
    return size
