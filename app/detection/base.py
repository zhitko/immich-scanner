from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class DetectedRegion:
    """Rotated rectangle in original-image pixels.

    `angle_deg` is clockwise-positive with the Y axis pointing down, the same
    as OpenCV `boxPoints` and canvas `rotate`. Detectors return it in
    (-45, 45] so `width` follows the side closest to horizontal.
    """

    center_x: float
    center_y: float
    width: float
    height: float
    angle_deg: float


class PhotoDetector(Protocol):
    def detect(self, image: np.ndarray) -> list[DetectedRegion]:
        """Return one region per print. Coordinates are pixels of `image`."""
