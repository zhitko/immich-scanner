import numpy as np

from app.detection.opencv_detector import OpenCvPhotoDetector
from app.imaging.crop import crop_rotated_rect
from tests.synthetic import make_bed, paint_photo


def test_white_lid_finds_each_print_and_ignores_dust() -> None:
    image = make_bed()
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 3
    expected = [(280, 240, (180, 40, 50)), (720, 620, (40, 90, 170)), (420, 1080, (40, 140, 80))]
    assert [region.center_y for region in regions] == sorted(region.center_y for region in regions)
    for center_x, center_y, color in expected:
        region = min(
            regions,
            key=lambda item: (item.center_x - center_x) ** 2 + (item.center_y - center_y) ** 2,
        )
        assert abs(region.center_x - center_x) < 25
        assert abs(region.center_y - center_y) < 25
        cropped = crop_rotated_rect(
            image, region.center_x, region.center_y, region.width, region.height, region.angle_deg
        )
        mean = _inner_mean(cropped)
        assert np.max(np.abs(mean - np.array(color))) < 20


def test_black_lid_is_separated_the_same_way() -> None:
    image = make_bed(
        background=(6, 6, 6),
        photos=[
            {"color": (210, 180, 40), "center": (300, 300), "size": (280, 180), "angle": 8},
            {"color": (200, 200, 210), "center": (680, 900), "size": (320, 220), "angle": -4},
        ],
    )
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 2


def test_white_print_on_a_white_lid_is_kept_because_of_its_edge() -> None:
    image = np.full((900, 700, 3), 255, np.uint8)
    paint_photo(image, (255, 255, 255), (340, 420), (300, 200), -6, border=12)
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 1
    assert abs(regions[0].center_x - 340) < 20
    assert abs(regions[0].center_y - 420) < 20


def test_only_dust_returns_no_regions() -> None:
    image = np.full((800, 600, 3), 255, np.uint8)
    image[20:28, 20:28] = (0, 0, 0)
    assert OpenCvPhotoDetector().detect(image) == []


def _inner_mean(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    return image[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4].mean(axis=(0, 1))
