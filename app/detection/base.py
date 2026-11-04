from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class DetectedRegion:
    """Rotated rectangle in original-image pixels.

    `angle_deg` uses OpenCV's minAreaRect convention: degrees, counter-clockwise
    positive, typically in the range [-90, 0).
    """

    center_x: float
    center_y: float
    width: float
    height: float
    angle_deg: float


class PhotoDetector(Protocol):
    def detect(self, image: np.ndarray) -> list[DetectedRegion]:
        """Return one region per print. Coordinates are pixels of `image`."""
