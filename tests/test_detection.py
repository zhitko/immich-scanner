import numpy as np

from app.detection.base import DetectedRegion
from app.detection.opencv_detector import OpenCvPhotoDetector, normalize_rect, overlap_fraction
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


def test_white_paper_margin_is_trimmed_from_the_crop() -> None:
    image = np.full((1400, 1000, 3), 248, np.uint8)
    paper, edge = (236, 234, 228), (150, 150, 150)
    for center, angle in (((330, 380), -4), ((620, 1000), 9)):
        paint_photo(image, paper, center, (420, 300), angle, border=3, border_color=edge)
        paint_photo(image, (70, 60, 55), center, (380, 260), angle, border=0)
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 2
    for region in regions:
        assert abs(region.width - 380) < 10
        assert abs(region.height - 260) < 10
        cropped = crop_rotated_rect(
            image, region.center_x, region.center_y, region.width, region.height, region.angle_deg
        )
        edges = np.concatenate(
            [
                cropped[:3].reshape(-1, 3),
                cropped[-3:].reshape(-1, 3),
                cropped[:, :3].reshape(-1, 3),
                cropped[:, -3:].reshape(-1, 3),
            ]
        )
        assert (edges.mean(axis=1) > 180).mean() < 0.02


def test_light_picture_without_a_margin_keeps_the_whole_print() -> None:
    image = np.full((1000, 900, 3), 248, np.uint8)
    edge = (150, 150, 150)
    paint_photo(image, (232, 230, 226), (450, 500), (500, 380), 3, border=3, border_color=edge)
    paint_photo(image, (60, 50, 45), (450, 520), (160, 200), 3, border=0)
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 1
    assert abs(regions[0].width - 500) < 10
    assert abs(regions[0].height - 380) < 10


def test_crops_keep_the_print_orientation() -> None:
    photos = [
        {"color": (180, 40, 50), "center": (300, 260), "size": (360, 220), "angle": 0},
        {"color": (40, 90, 170), "center": (700, 300), "size": (200, 320), "angle": 0},
        {"color": (40, 140, 80), "center": (320, 800), "size": (380, 240), "angle": 8},
        {"color": (150, 120, 40), "center": (720, 900), "size": (220, 340), "angle": -10},
    ]
    image = make_bed(photos=photos)
    regions = OpenCvPhotoDetector().detect(image)
    assert len(regions) == 4
    for photo in photos:
        center_x, center_y = photo["center"]  # type: ignore[misc]
        width, height = photo["size"]  # type: ignore[misc]
        region = min(
            regions,
            key=lambda item: (item.center_x - center_x) ** 2 + (item.center_y - center_y) ** 2,
        )
        assert -45 < region.angle_deg <= 45
        assert abs(region.angle_deg - float(photo["angle"])) < 2  # type: ignore[arg-type]
        assert abs(region.width - width) < 12
        assert abs(region.height - height) < 12


def test_rect_normalization_prefers_the_smallest_tilt() -> None:
    assert normalize_rect(150, 300, -90) == (300, 150, 0)
    assert normalize_rect(150, 300, -85) == (300, 150, 5)
    assert normalize_rect(300, 150, 88) == (150, 300, -2)
    assert normalize_rect(300, 150, -5) == (300, 150, -5)


def test_overlap_fraction() -> None:
    a = DetectedRegion(100, 100, 100, 50, 0)
    assert overlap_fraction(a, a) > 0.99
    assert overlap_fraction(a, DetectedRegion(400, 400, 100, 50, 0)) == 0
    half = overlap_fraction(a, DetectedRegion(150, 100, 100, 50, 0))
    assert 0.45 < half < 0.55


def test_thin_l_shaped_shadow_is_not_a_photo() -> None:
    image = np.full((900, 700, 3), 250, np.uint8)
    image[100:112, 100:600] = (30, 30, 30)
    image[100:700, 100:112] = (30, 30, 30)
    assert OpenCvPhotoDetector().detect(image) == []


def test_only_dust_returns_no_regions() -> None:
    image = np.full((800, 600, 3), 255, np.uint8)
    image[20:28, 20:28] = (0, 0, 0)
    assert OpenCvPhotoDetector().detect(image) == []


def _inner_mean(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    return image[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4].mean(axis=(0, 1))
