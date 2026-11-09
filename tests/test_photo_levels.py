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


def test_contrast_balances_gradient_without_losing_texture() -> None:
    # Repeated fine detail under a broad illumination gradient, with true black
    # and white reference rows so a global stretch cannot fix the imbalance.
    texture = np.tile(np.array([[-12], [12]]), (128, 512))
    gray = np.clip(texture + np.linspace(55, 200, 512), 0, 255).astype(np.uint8)
    gray[:2] = 0
    gray[-2:] = 255
    image = np.repeat(gray[:, :, None], 3, axis=2)
    before = image.copy()
    result = restore_contrast(image)
    left, right = result[20:-20, 20:100, 0], result[20:-20, -100:-20, 0]
    original_gap = gray[20:-20, -100:-20].mean() - gray[20:-20, 20:100].mean()
    assert right.mean() - left.mean() < original_gap * 0.8
    assert np.mean(left[1::2].astype(float) - left[::2]) > 18
    assert np.mean(right[1::2].astype(float) - right[::2]) > 18
    np.testing.assert_array_equal(result[:2], image[:2])
    np.testing.assert_array_equal(result[-2:], image[-2:])
    np.testing.assert_array_equal(result[:, :, 0], result[:, :, 2])
    np.testing.assert_array_equal(image, before)


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


def test_contrast_reduces_local_veil_and_recovers_detail() -> None:
    # Identical dark/light texture, with an additive veil in the upper left.
    y, x = np.mgrid[:256, :384]
    clean = np.where((y // 4) % 2, 160.0, 24.0)
    veil = 80 * np.exp(-((x / 150) ** 2 + (y / 130) ** 2))
    gray = np.rint(clean * (1 - veil / 255) + veil).astype(np.uint8)
    image = np.repeat(gray[:, :, None], 3, axis=2)
    result = restore_contrast(image)[:, :, 0]
    patch = np.s_[16:80, 16:80]
    dark = clean[patch] == 24
    before, after = gray[patch], result[patch]
    assert after[dark].mean() < before[dark].mean() - 10
    assert after[~dark].mean() - after[dark].mean() > (
        before[~dark].mean() - before[dark].mean()
    ) * 1.1
