from dataclasses import dataclass

import cv2
import numpy as np

from app.detection.base import DetectedRegion
from app.imaging.crop import crop_rotated_rect, resize_max_edge


@dataclass(frozen=True)
class DetectorConfig:
    max_edge: int = 1400
    min_area_ratio: float = 0.004
    min_side_ratio: float = 0.02
    border_fraction: float = 0.012
    min_tolerance: int = 12
    max_tolerance: int = 36
    min_fill_ratio: float = 0.45
    edge_inset_px: float = 1.0
    trim_margins: bool = True
    trim_patch_edge: int = 1200
    trim_light_drops: tuple[int, ...] = (12, 30)
    trim_line_fill: float = 0.9
    trim_max_fraction: float = 0.1
    trim_run_fraction: float = 0.015
    trim_segments: int = 8
    trim_max_tilt_deg: float = 1.5
    trim_extra_fraction: float = 0.002


class OpenCvPhotoDetector:
    """Separate prints from a flatbed lid by flood-filling the background.

    The lid is usually white or black. Seeds are taken from border pixels close
    to the border median, so both lids work, and a print whose interior matches
    the lid is still kept when its edge stops the flood. The close kernel stays
    smaller than a typical 5 mm gap so neighbouring prints are not merged.

    Each rectangle is then pulled in past light lines along its sides: the
    white paper margin of old prints and slivers of lid where the fitted
    rectangle overshoots the paper. Each side is checked against a tight
    lid-coloured band and a looser paper-coloured one, so a lid sliver is
    still found next to a light picture background. A side whose light band
    runs deeper than `trim_max_fraction` is left alone, since that is a light
    picture rather than a margin.
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
        foreground, lid_level = self._foreground_mask(gray)
        contours, _hierarchy = cv2.findContours(
            foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        small_h, small_w = gray.shape
        min_area = self._config.min_area_ratio * small_h * small_w
        min_side = self._config.min_side_ratio * min(small_h, small_w)
        inset = self._config.edge_inset_px * 2
        found: list[DetectedRegion] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            (center_x, center_y), (rect_w, rect_h), angle = cv2.minAreaRect(contour)
            if rect_w < min_side or rect_h < min_side:
                continue
            if rect_w * rect_h > 0.98 * small_w * small_h:
                continue
            if area < self._config.min_fill_ratio * rect_w * rect_h:
                continue
            rect_w, rect_h, angle = normalize_rect(rect_w, rect_h, angle)
            rect_w = max(1.0, rect_w - inset)
            rect_h = max(1.0, rect_h - inset)
            found.append(
                DetectedRegion(
                    center_x=float(center_x) * scale_x,
                    center_y=float(center_y) * scale_y,
                    width=float(rect_w) * scale_x,
                    height=float(rect_h) * scale_y,
                    angle_deg=float(angle),
                )
            )
        if self._config.trim_margins and found:
            full_gray = gray if small is image else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            found = [self._trim_margins(full_gray, region, lid_level) for region in found]
        return sort_reading_order(found)

    def _trim_margins(
        self, gray: np.ndarray, region: DetectedRegion, lid_level: float
    ) -> DetectedRegion:
        config = self._config
        patch = crop_rotated_rect(
            gray, region.center_x, region.center_y, region.width, region.height, region.angle_deg
        )
        patch_h, patch_w = patch.shape[:2]
        patch = resize_max_edge(patch, config.trim_patch_edge)
        scale_x = patch_w / patch.shape[1]
        scale_y = patch_h / patch.shape[0]
        light_level = max(lid_level, 220.0)
        run = max(6, int(round(min(patch.shape[:2]) * config.trim_run_fraction)))

        def depth(lines: np.ndarray) -> float:
            return max(
                _side_depth(
                    lines,
                    light_level - drop,
                    config.trim_line_fill,
                    config.trim_max_fraction,
                    run,
                    config.trim_segments,
                    config.trim_max_tilt_deg,
                )
                for drop in config.trim_light_drops
            )

        extra = config.trim_extra_fraction * min(region.width, region.height)
        top, bottom, left, right = (
            side + extra if side > 0 else 0.0
            for side in (
                depth(patch) * scale_y,
                depth(patch[::-1]) * scale_y,
                depth(patch.T) * scale_x,
                depth(patch.T[::-1]) * scale_x,
            )
        )
        width = region.width - left - right
        height = region.height - top - bottom
        if width < region.width * 0.5 or height < region.height * 0.5:
            return region
        shift_x = (left - right) / 2
        shift_y = (top - bottom) / 2
        radians = np.deg2rad(region.angle_deg)
        cos, sin = float(np.cos(radians)), float(np.sin(radians))
        return DetectedRegion(
            center_x=region.center_x + shift_x * cos - shift_y * sin,
            center_y=region.center_y + shift_x * sin + shift_y * cos,
            width=width,
            height=height,
            angle_deg=region.angle_deg,
        )

    def _foreground_mask(self, gray: np.ndarray) -> tuple[np.ndarray, float]:
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
        opened = cv2.morphologyEx(
            closed,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size)),
        )
        return opened, median


def normalize_rect(width: float, height: float, angle: float) -> tuple[float, float, float]:
    """Express a rotated rectangle with its smallest tilt, in (-45, 45].

    OpenCV reports `minAreaRect` angles in [-90, 0) or (0, 90] depending on
    the version, so an upright landscape print can come back as a portrait
    rectangle turned by 90 degrees. Cropping that would lay the photo on its side.
    """

    while angle > 45:
        angle -= 90
        width, height = height, width
    while angle <= -45:
        angle += 90
        width, height = height, width
    return width, height, angle


def overlap_fraction(a: DetectedRegion, b: DetectedRegion) -> float:
    """Intersection area divided by the smaller rectangle's area."""

    smaller = min(a.width * a.height, b.width * b.height)
    if smaller <= 0:
        return 0.0
    kind, points = cv2.rotatedRectangleIntersection(
        ((a.center_x, a.center_y), (a.width, a.height), a.angle_deg),
        ((b.center_x, b.center_y), (b.width, b.height), b.angle_deg),
    )
    if kind == cv2.INTERSECT_NONE or points is None or len(points) < 3:
        return 0.0
    hull = cv2.convexHull(points.astype(np.float32))
    return float(cv2.contourArea(hull)) / smaller


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


def _side_depth(
    lines: np.ndarray,
    threshold: float,
    line_fill: float,
    max_fraction: float,
    run: int,
    segments: int,
    max_tilt_deg: float,
) -> float:
    """Rows to drop from the top of `lines` so no margin is left along it.

    The side is measured in segments and a robust line is fitted through
    their depths, so a margin that thins out along a slightly tilted print is
    cleared at its deepest end. A real margin has a straight inner edge; when
    most segments disagree with the line, the light band is picture content
    and the side is left alone. Ends of each row are skipped because corners
    of a tilted print are lid.
    """

    span = lines.shape[1]
    skip = span // 10
    core = lines[:, skip : span - skip]
    limit = int(lines.shape[0] * max_fraction)
    if limit < 1 or core.shape[1] < segments:
        return 0.0
    light = core[: limit + run] >= threshold
    positions: list[float] = []
    depths: list[int] = []
    offset = skip
    for segment in np.array_split(light, segments, axis=1):
        depth = _margin_depth(segment.mean(axis=1) >= line_fill, limit, run)
        if depth is not None:
            positions.append(offset + segment.shape[1] / 2)
            depths.append(depth)
        offset += segment.shape[1]
    if len(depths) < max(2, segments // 2):
        return 0.0
    x = np.array(positions)
    y = np.array(depths, dtype=np.float64)
    max_slope = float(np.tan(np.deg2rad(max_tilt_deg)))
    slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(y)) for j in range(i + 1, len(y))]
    slope = float(np.clip(np.median(slopes), -max_slope, max_slope))
    intercept = float(np.median(y - slope * x))
    inliers = np.abs(y - (intercept + slope * x)) <= max(2.0, run / 2)
    if inliers.sum() < max(segments / 2, 0.75 * len(y)):
        return 0.0
    if inliers.sum() >= 2:
        slope, intercept = np.polyfit(x[inliers], y[inliers], 1)
        slope = float(np.clip(slope, -max_slope, max_slope))
        intercept = float(np.mean(y[inliers] - slope * x[inliers]))
    deepest = max(intercept, intercept + slope * span)
    return float(np.clip(deepest, 0, limit))


def _margin_depth(margin: np.ndarray, limit: int, run: int) -> int | None:
    """Index of the first picture row, given which rows look like margin.

    The picture starts at the first `run` non-margin rows in a row, so a thin
    shadow line at the paper edge does not end the margin early. None means
    the rows are light all the way down, which says nothing about a margin.
    """

    picture = ~margin
    for start in range(limit):
        if picture[start : start + run].all():
            if start == 0 or margin[:start].mean() < 0.5:
                return 0
            return start
    return None


def _odd_size(value: float) -> int:
    size = max(3, int(round(value)))
    if size % 2 == 0:
        size += 1
    return size
