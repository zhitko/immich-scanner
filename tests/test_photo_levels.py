import numpy as np
import pytest

from app.retouch.engine import OnnxRetoucher
from app.retouch.levels import _restore_red_fade, correct_color_cast, restore_contrast
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


def test_color_balance_corrects_nonlinear_fading_before_contrast() -> None:
    ramp = np.tile(np.linspace(0, 1, 512, dtype=np.float32), (64, 1))
    bow = 4 * ramp * (1 - ramp)
    image = np.stack((150 + 50 * ramp - 3 * bow, 103 + 50 * ramp,
                      102 + 50 * ramp + bow), axis=2)
    result = correct_color_cast(image)
    center = result[:, 180:330]
    assert np.ptp(center.mean(axis=(0, 1))) < 2
    assert np.ptp(restore_contrast(result)[:, 180:330].mean(axis=(0, 1))) < 8
    assert result.dtype == np.float32
    assert np.all(np.diff(result, axis=1) >= 0)


def test_color_balance_preserves_full_range_scene_colors() -> None:
    ramp = np.tile(np.linspace(0, 255, 512, dtype=np.float32), (64, 1))
    image = np.stack((ramp, ramp ** 2 / 255, ramp), axis=2)
    result = correct_color_cast(image)
    # Full-range color is not fading; a green-deficient scene remains so.
    assert result[:, 256, 0].mean() - result[:, 256, 1].mean() > 60


def _red_faded_ramp() -> np.ndarray:
    ramp = np.tile(np.linspace(0, 1, 256, dtype=np.float32), (192, 1))
    return np.stack((150 + 55 * ramp ** 1.2, 103 + 52 * ramp,
                     101 + 49 * ramp ** 0.9), axis=2)


def test_automatic_red_fade_restores_neutrals_without_cyan_overshoot() -> None:
    image = _red_faded_ramp()
    before = image.copy()
    result = _restore_red_fade(image, image)
    assert result is not None
    central = result[:, 40:215]
    assert np.ptp(central.mean(axis=(0, 1))) < 4
    assert np.min(central[:, :, 0] - central[:, :, 1]) > -1
    assert np.all(np.diff(result, axis=1) >= 0)
    assert result.dtype == np.float32
    np.testing.assert_array_equal(image, before)
    np.testing.assert_allclose(correct_color_cast(image), result)


def test_red_fade_reference_ignores_border_and_isolated_damage() -> None:
    image = _red_faded_ramp()
    clean = _restore_red_fade(image, image)
    damaged = image.copy()
    damaged[:8] = (255, 0, 180)
    damaged[-8:] = 255
    damaged[:, :10] = 0
    damaged[:, -10:] = (255, 40, 120)
    damaged[::23, ::19] = 255
    result = _restore_red_fade(damaged, damaged)
    assert result is not None
    mask = np.ones(image.shape[:2], dtype=bool)
    mask[:10] = mask[-10:] = False
    mask[:, :12] = mask[:, -12:] = False
    mask[::23, ::19] = False
    assert np.abs(result[mask] - clean[mask]).mean() < 1


@pytest.mark.parametrize("kind", ["neutral", "full_range_red", "flat", "mixed"])
def test_red_fade_does_not_activate_without_consistent_fading(kind) -> None:
    image = _red_faded_ramp()
    if kind == "neutral":
        image[:] = image.mean(axis=2, keepdims=True)
    elif kind == "full_range_red":
        ramp = np.linspace(0, 1, image.shape[1])
        image[:] = np.stack((30 + 220 * ramp, 180 * ramp, 160 * ramp), axis=1)
    elif kind == "flat":
        image[:] = (175, 120, 115)
    else:
        image[:, :128] = image[:, :128, ::-1]
    assert _restore_red_fade(image, image) is None


def test_contrast_deepens_faded_blacks_and_preserves_neutrality() -> None:
    ramp = np.tile(np.arange(110, 221, dtype=np.uint8), (32, 1))
    image = np.repeat(ramp[:, :, None], 3, axis=2)
    result = restore_contrast(image)
    assert np.percentile(result, 5) < 40
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


def test_contrast_keeps_detail_in_dark_subjects_on_bright_background() -> None:
    # A thin textured dark band (a crowd) under a large bright sky, as in a
    # faded print. Holding back the sky must not crush the crowd to black.
    y, x = np.mgrid[:256, :384]
    gray = np.full((256, 384), 212.0)
    band = y >= 232
    gray[band] = 76 + 14 * np.where((x[band] // 3) % 2, 1, -1)
    gray[:2] = 40
    image = np.repeat(np.rint(gray).astype(np.uint8)[:, :, None], 3, axis=2)
    crowd = restore_contrast(image)[236:252, :, 0].astype(float)
    assert crowd.mean() > 45
    assert crowd.std() > 20
