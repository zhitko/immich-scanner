import cv2
import numpy as np

from app.imaging.crop import (
    apply_quarter_turns,
    crop_rotated_rect,
    crop_signature,
    rotated_rect_corners,
)


def test_axis_aligned_crop_matches_the_rectangle() -> None:
    image = np.zeros((80, 100, 3), np.uint8)
    image[20:50, 10:50] = (10, 20, 30)
    cropped = crop_rotated_rect(image, 30, 35, 40, 30, 0)
    assert cropped.shape == (30, 40, 3)
    assert np.all(cropped[4:-4, 4:-4] == (10, 20, 30))


def test_rotated_sprite_round_trips() -> None:
    sprite = np.zeros((40, 60, 3), np.uint8)
    sprite[:20, :30] = (200, 0, 0)
    sprite[:20, 30:] = (0, 180, 0)
    sprite[20:, :30] = (0, 0, 170)
    sprite[20:, 30:] = (180, 180, 0)
    bed = np.full((200, 220, 3), 255, np.uint8)
    center = (110.0, 90.0)
    angle = -18.0
    _paste(bed, sprite, center, angle)
    cropped = crop_rotated_rect(bed, center[0], center[1], 60, 40, angle)
    assert cropped.shape[0] == 40
    assert cropped.shape[1] == 60
    assert _quadrant(cropped, 0, 0)[0] > 150
    assert _quadrant(cropped, 0, 1)[1] > 130
    assert _quadrant(cropped, 1, 0)[2] > 120
    assert _quadrant(cropped, 1, 1)[0] > 130
    assert _quadrant(cropped, 1, 1)[1] > 130


def test_quarter_turns_are_clockwise() -> None:
    image = np.array([[[1, 0, 0], [2, 0, 0]], [[3, 0, 0], [4, 0, 0]]], np.uint8)
    turned = apply_quarter_turns(image, 1)
    assert turned[0, 0, 0] == 3
    assert turned[0, 1, 0] == 1
    assert turned[1, 0, 0] == 4
    assert turned[1, 1, 0] == 2
    assert np.array_equal(apply_quarter_turns(image, 4), image)


def test_signature_changes_when_the_crop_changes() -> None:
    first = crop_signature(1, 2, 3, 4, 5, 0)
    assert first == crop_signature(1, 2, 3, 4, 5, 4)
    assert first != crop_signature(1, 2, 3, 4, 5, 1)


def _paste(bed: np.ndarray, sprite: np.ndarray, center: tuple[float, float], angle: float) -> None:
    height, width = sprite.shape[:2]
    corners = rotated_rect_corners(center[0], center[1], width, height, angle)
    source = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, corners)
    size = (bed.shape[1], bed.shape[0])
    warped = cv2.warpPerspective(sprite, matrix, size)
    mask = cv2.warpPerspective(np.full(sprite.shape[:2], 255, np.uint8), matrix, size)
    bed[mask > 128] = warped[mask > 128]


def _quadrant(image: np.ndarray, row: int, column: int) -> np.ndarray:
    height, width = image.shape[:2]
    y0, y1 = (4, height // 2 - 2) if row == 0 else (height // 2 + 2, height - 4)
    x0, x1 = (4, width // 2 - 2) if column == 0 else (width // 2 + 2, width - 4)
    return image[y0:y1, x0:x1].mean(axis=(0, 1))
