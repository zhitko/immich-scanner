from types import SimpleNamespace

import numpy as np
import pytest

from app.retouch.catalog import CATALOG, specs_for
from app.retouch.detection import learned_scratch_mask, scratch_probabilities
from app.retouch.engine import MissingWeights, OnnxRetoucher
from app.retouch.options import RetouchOptions, expected_retouch_signature, retouch_matches


class Detector:
    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, _outputs, feeds):
        tensor = feeds["input"]
        assert tensor.dtype == np.float32
        assert tensor.shape == (1, 1, 256, 512)
        assert tensor.min() == -1 and tensor.max() == 1
        result = np.full_like(tensor, 0.6)
        result[:, :, 80:180, 120:125] = 0.95
        return [result]


def test_detector_preserves_uncertain_texture_and_maps_damage_to_source_resolution():
    image = np.zeros((512, 1024, 3), np.uint8)
    image[:, 512:] = 255
    mask = learned_scratch_mask(Detector(), image)
    assert mask.shape == image.shape[:2]
    assert mask.dtype == bool
    assert mask[170:350, 242:248].all()
    assert not mask[:, 300:].any()
    assert not mask[:150].any()


@pytest.mark.parametrize("value", [np.nan, np.inf, -0.1, 1.1])
def test_detector_rejects_invalid_probabilities(value):
    class Invalid(Detector):
        def run(self, _outputs, feeds):
            return [np.full_like(feeds["input"], value)]

    with pytest.raises(RuntimeError, match="invalid probabilities"):
        scratch_probabilities(Invalid(), np.zeros((256, 512, 3), np.uint8))


def test_scratch_repair_requires_detector_and_inpaint_weights(tmp_path):
    needed = specs_for(upscale=False, denoise=False, faces=False, colorize=False, scratches=True)
    assert [spec.id for spec in needed] == ["scratch-detection", "inpaint"]
    (tmp_path / CATALOG["inpaint"].filename).touch()
    with pytest.raises(MissingWeights, match="scratch-detection.onnx"):
        OnnxRetoucher(tmp_path).apply(
            np.zeros((32, 32, 3), np.uint8), RetouchOptions(scratches=True)
        )


def test_uncertain_photo_skips_inpainting_and_finishes_progress(tmp_path, monkeypatch):
    for key in ("scratch-detection", "inpaint"):
        (tmp_path / CATALOG[key].filename).touch()

    class Uncertain(Detector):
        def run(self, _outputs, feeds):
            return [np.full_like(feeds["input"], 0.6)]

    retoucher = OnnxRetoucher(tmp_path)
    opened = []

    def session(spec):
        opened.append(spec.id)
        assert spec.id == "scratch-detection"
        return Uncertain()

    monkeypatch.setattr(retoucher, "_session", session)
    image = np.random.default_rng(12).integers(0, 256, (128, 64, 3), dtype=np.uint8)
    progress, stages = [], []
    result = retoucher.apply(image, RetouchOptions(scratches=True), progress.append, stages.append)
    assert np.array_equal(result, image)
    assert opened == ["scratch-detection"]
    assert progress[-1] == 99
    assert stages == ["Detecting scratches"]


def test_old_scratch_derivatives_are_stale_but_new_results_are_current():
    from app.models import Region

    region = Region(
        center_x=100,
        center_y=100,
        width=100,
        height=100,
        angle_deg=0,
        quarter_turns=0,
        retouch_scratches=True,
        retouch_path="retouch/example.png",
    )
    current = expected_retouch_signature(region)
    region.retouch_signature = current.replace("|scratch-v2", "")
    assert not retouch_matches(region)
    region.retouch_signature = current
    assert retouch_matches(region)


def test_accepted_damage_reaches_lama_with_progress_and_stage_updates(tmp_path, monkeypatch):
    for key in ("scratch-detection", "inpaint"):
        (tmp_path / CATALOG[key].filename).touch()

    class Damage(Detector):
        def run(self, _outputs, feeds):
            result = np.zeros_like(feeds["input"])
            result[:, :, 80:180, 120:125] = 0.95
            return [result]

    class Lama:
        def get_inputs(self):
            return [
                SimpleNamespace(name="image", shape=[1, 3, 512, 512]),
                SimpleNamespace(name="mask", shape=[1, 1, 512, 512]),
            ]

        def run(self, _outputs, feeds):
            assert feeds["mask"].max() == 1
            return [np.full_like(feeds["image"], 200)]

    retoucher = OnnxRetoucher(tmp_path)
    monkeypatch.setattr(
        retoucher, "_session", lambda spec: Damage() if spec.id == "scratch-detection" else Lama()
    )
    image = np.full((256, 512, 3), 80, np.uint8)
    progress, stages = [], []
    result = retoucher.apply(image, RetouchOptions(scratches=True), progress.append, stages.append)
    assert result[100, 122, 0] == 200
    assert np.array_equal(result[:, 300:], image[:, 300:])
    assert progress == sorted(set(progress))
    assert progress[-1] == 99
    assert stages == ["Detecting scratches", "Filling scratches"]
