import cv2
import numpy as np
import pytest
from PIL import Image

from app.imaging.crop import upright_crop
from app.imaging.io import as_byte_rgb, load_rgb, save_rgb
from app.retouch.engine import OnnxRetoucher
from app.retouch.imageops import masked_tiles, tiled_map, unit_to_rgb
from app.retouch.options import RetouchOptions


@pytest.mark.parametrize("extension", ["png", "tiff"])
@pytest.mark.parametrize("grayscale", [False, True])
def test_load_preserves_16_bit_samples(tmp_path, extension, grayscale):
    values = np.arange(32000, 33024, dtype=np.uint16).reshape(32, 32)
    rgb = np.stack((values, values + 1000, values + 2000), axis=2)
    path = tmp_path / f"scan.{extension}"
    assert cv2.imwrite(str(path), values if grayscale else rgb[..., ::-1])
    working, _ = load_rgb(path, working=True)
    expected = np.repeat(values[..., None], 3, axis=2) if grayscale else rgb
    assert working.dtype == np.float32
    np.testing.assert_allclose(working * 257, expected, atol=0.004)
    assert np.unique(working[..., 0]).size == 1024
    preview, _ = load_rgb(path)
    assert preview.dtype == np.uint8
    np.testing.assert_array_equal(preview, as_byte_rgb(working))


def test_faded_ramp_retains_precision_through_crop_levels_and_export(tmp_path):
    ramp = np.tile(np.linspace(30000, 44000, 1024, dtype=np.uint16), (32, 1))
    path = tmp_path / "scan.png"
    assert cv2.imwrite(str(path), np.repeat(ramp[..., None], 3, axis=2))
    image, _ = load_rgb(path, working=True)
    crop = upright_crop(image, 512, 16, 1024, 32, 0, 0)
    result = OnnxRetoucher(tmp_path).apply(crop, RetouchOptions(color_balance=True, contrast=True))
    assert result.dtype == np.float32
    assert np.unique(result[16, :, 0]).size > 900
    # A source quantized before stretching can only retain ~55 levels.
    assert np.unique(as_byte_rgb(result)[16, :, 0]).size > 180
    output = tmp_path / "result.png"
    save_rgb(result, output, "png")
    np.testing.assert_array_equal(np.array(Image.open(output)), as_byte_rgb(result))


def test_neural_conversion_and_tile_blending_keep_fractional_levels():
    image = np.full((40, 48, 3), 100.125, np.float32)
    converted = unit_to_rgb(image / 255)
    tiled = tiled_map(converted, lambda tile: tile, tile=16, overlap=4)
    masked = masked_tiles(
        tiled,
        np.ones((40, 48), bool),
        lambda tile, mask: tile,
        tile_h=16,
        tile_w=16,
        overlap=4,
    )
    assert masked.dtype == np.float32
    np.testing.assert_allclose(masked, image, atol=0.0001)
