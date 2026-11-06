import numpy as np
import pytest

from app.retouch.engine import OnnxRetoucher
from app.retouch.levels import correct_color_cast, restore_contrast
from app.retouch.options import RetouchOptions, option_token, options_from_token


def test_color_balance_removes_cast_from_faded_neutrals() -> None:
    ramp = np.tile(np.linspace(0, 1, 256), (32, 1))
    image = np.stack((80 + ramp * 160, 30 + ramp * 120, 20 + ramp * 90), axis=2)
    image = image.astype(np.uint8)
    before = image.copy()
    result = correct_color_cast(image)
    assert np.abs(result.astype(float).mean(axis=(0, 1)) - result.mean()).max() < 2
    assert result.shape == image.shape
    assert result.dtype == np.uint8
    np.testing.assert_array_equal(image, before)


def test_contrast_deepens_faded_blacks_and_preserves_neutrality() -> None:
    ramp = np.tile(np.arange(110, 221, dtype=np.uint8), (32, 1))
    image = np.repeat(ramp[:, :, None], 3, axis=2)
    result = restore_contrast(image)
    assert np.percentile(result, 5) < 30
    assert np.percentile(result, 95) > 225
    np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
    np.testing.assert_array_equal(result[:, :, 1], result[:, :, 2])
    assert np.all(np.diff(result[0, :, 0].astype(int)) >= 0)


@pytest.mark.parametrize("correction", [correct_color_cast, restore_contrast])
def test_flat_prints_are_not_amplified(correction) -> None:
    image = np.full((40, 50, 3), (190, 170, 155), dtype=np.uint8)
    np.testing.assert_array_equal(correction(image), image)


def test_levels_run_without_weights_and_report_progress(tmp_path) -> None:
    image = np.random.default_rng(42).integers(80, 220, (64, 64, 3), dtype=np.uint8)
    options = RetouchOptions(color_balance=True, contrast=True)
    stages, progress = [], []
    result = OnnxRetoucher(tmp_path).apply(image, options, progress.append, stages.append)
    assert stages == ["Correcting color cast", "Restoring contrast"]
    assert progress == sorted(progress)
    # The job reserves 100% for saving the derivative and preview.
    assert progress[-1] == 99
    assert result.shape == image.shape
    assert options_from_token(option_token(options)) == options
    assert options_from_token("u0d0f0c0s0") == RetouchOptions()
    assert options_from_token("u1f0c0s0") == RetouchOptions(upscale=True, denoise=True)
