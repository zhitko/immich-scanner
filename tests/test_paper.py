import numpy as np
import pytest

from app.retouch.engine import OnnxRetoucher
from app.retouch.options import RetouchOptions, option_token, options_from_token
from app.retouch.paper import reduce_paper_embossed, reduce_paper_mesh
from app.schemas import RetouchRequest


@pytest.mark.parametrize("process", [reduce_paper_mesh, reduce_paper_embossed])
@pytest.mark.parametrize("shape", [(31, 45), (257, 281)])
def test_paper_preserves_flat_fractional_color_and_borders(process, shape):
    image = np.empty((*shape, 3), np.float32)
    image[:] = (83.25, 124.5, 170.75)
    result = process(image)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, image, atol=.002)


def test_mesh_removes_periodic_pattern_without_losing_broad_tone():
    y, x = np.mgrid[:384, :384]
    base = 100 + 30 * x / 384 + 15 * np.sin(y / 100)
    texture = 15 * np.cos(2 * np.pi * (x / 8 + y / 16))
    image = np.repeat((base + texture)[..., None], 3, axis=2).astype(np.float32)
    result = reduce_paper_mesh(image)[..., 0]
    assert np.std(result - base) < np.std(texture) * .5
    assert abs(result.mean() - base.mean()) < .1


def test_embossed_reduces_stationary_texture_and_keeps_large_edge():
    rng = np.random.default_rng(9)
    base = np.full((256, 320), 100, np.float32)
    base[:, 160:] = 160
    image = np.repeat((base + rng.normal(0, 10, base.shape))[..., None], 3, axis=2)
    result = reduce_paper_embossed(image.astype(np.float32))[..., 0]
    assert np.std(result[20:230, 20:130] - base[20:230, 20:130]) < 8
    assert result[:, 200:280].mean() - result[:, 40:120].mean() > 55


@pytest.mark.parametrize("flag", ["paper_mesh", "paper_embossed"])
def test_paper_options_and_no_model_pipeline(flag, tmp_path):
    options = RetouchOptions(**{flag: True})
    assert options_from_token(option_token(options)) == options
    assert options.any_selected()
    assert getattr(RetouchRequest(**{flag: True}), flag)
    stages, progress = [], []
    image = np.full((128, 128, 3), 127.5, np.float32)
    result = OnnxRetoucher(tmp_path).apply(image, options, progress.append, stages.append)
    np.testing.assert_allclose(result, image, atol=.002)
    assert len(stages) == 1
    assert progress[-1] == 99
    old = options_from_token("u0d0f0c0s0b0t0")
    assert old is not None and not old.paper_mesh and not old.paper_embossed
