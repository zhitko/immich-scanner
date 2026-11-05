import cv2
import numpy as np


def crop_signature(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
    quarter_turns: int,
) -> str:
    return (
        f"{center_x:.2f}|{center_y:.2f}|{width:.2f}|{height:.2f}|"
        f"{angle_deg:.2f}|{quarter_turns % 4}"
    )


def rotated_rect_corners(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
) -> np.ndarray:
    """Corners in the order top-left, top-right, bottom-right, bottom-left.

    The angle turns clockwise on screen (Y down), like OpenCV `boxPoints`.
    Width runs from the first corner to the second.
    """

    radians = np.deg2rad(angle_deg)
    cos, sin = np.cos(radians), np.sin(radians)
    half_w, half_h = width / 2, height / 2
    local = ((-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h))
    return np.array(
        [(center_x + x * cos - y * sin, center_y + x * sin + y * cos) for x, y in local],
        dtype=np.float32,
    )


def crop_rotated_rect(
    image: np.ndarray,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
) -> np.ndarray:
    crop_w = max(1, int(round(width)))
    crop_h = max(1, int(round(height)))
    source = rotated_rect_corners(center_x, center_y, width, height, angle_deg)
    destination = np.array(
        [[0, 0], [crop_w, 0], [crop_w, crop_h], [0, crop_h]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(
        image,
        matrix,
        (crop_w, crop_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def upright_crop(
    image: np.ndarray,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle_deg: float,
    quarter_turns: int,
) -> np.ndarray:
    cropped = crop_rotated_rect(image, center_x, center_y, width, height, angle_deg)
    return apply_quarter_turns(cropped, quarter_turns)


def apply_quarter_turns(image: np.ndarray, quarter_turns: int) -> np.ndarray:
    """Rotate clockwise by 90 degrees for each turn."""

    turns = quarter_turns % 4
    if turns == 0:
        return image
    return np.rot90(image, k=-turns)


def resize_max_edge(image: np.ndarray, max_edge: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)
