from types import SimpleNamespace

import numpy as np
import pytest

from app.retouch.catalog import CATALOG, specs_for
from app.retouch.detection import learned_scratch_mask, repair_mask, scratch_probabilities
from app.retouch.engine import MissingWeights, OnnxRetoucher
from app.retouch.options import RetouchOptions, expected_retouch_signature, retouch_matches


class Detector:
    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, _outputs, feeds):
        tensor = feeds["input"]
        assert tensor.dtype == np.float32
        assert tensor.shape in ((1, 1, 256, 512), (1, 1, 512, 1024))
        assert tensor.min() == -1 and tensor.max() == 1
        result = np.full_like(tensor, 0.6)
        scale = tensor.shape[2] // 256
        result[:, :, 80 * scale : 180 * scale, 120 * scale : 125 * scale] = 0.95
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
    region.retouch_signature = current.replace("|scratch-v5", "")
    assert not retouch_matches(region)
    for revision in ("scratch-v2", "scratch-v3", "scratch-v4"):
        region.retouch_signature = current.replace("scratch-v5", revision)
        assert not retouch_matches(region)
    region.retouch_signature = current
    assert retouch_matches(region)


def test_accepted_damage_reaches_lama_with_progress_and_stage_updates(tmp_path, monkeypatch):
    for key in ("scratch-detection", "inpaint"):
        (tmp_path / CATALOG[key].filename).touch()

    class Damage(Detector):
        def run(self, _outputs, feeds):
            result = np.zeros_like(feeds["input"])
            scale = result.shape[2] // 256
            result[:, :, 80 * scale : 180 * scale, 120 * scale : 125 * scale] = 0.95
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


def test_repair_mask_covers_crease_edges_but_not_disconnected_weak_texture():
    probabilities = np.zeros((1024, 1024), dtype=np.float32)
    probabilities[500:503, 100:900] = 0.95
    probabilities[495:510, 100:900] = np.maximum(probabilities[495:510, 100:900], 0.3)
    probabilities[600:620, 100:900] = 0.6
    mask = repair_mask(probabilities)
    assert mask[495:510, 100:900].all()
    assert not mask[600:620].any()
    assert not mask[:490].any()
    assert not mask[515:].any()


def test_repair_mask_cannot_flood_connected_uncertain_fabric():
    probabilities = np.full((1024, 1024), 0.6, dtype=np.float32)
    assert not repair_mask(probabilities).any()
    probabilities[500:503, 500:503] = 0.95
    mask = repair_mask(probabilities)
    assert mask[500:503, 500:503].all()
    assert not mask[:490].any()
    assert not mask[513:].any()
    assert not mask[:, :490].any()
    assert not mask[:, 513:].any()


def test_second_scale_rejects_necklace_but_keeps_confirmed_crease_edges():
    coarse = np.zeros((1024, 1024), dtype=np.float32)
    coarse[100:900, 100:110] = 0.95  # Necklace mistaken for a scratch.
    coarse[495:510, 300:900] = 0.3
    coarse[500:503, 300:900] = 0.95  # Real crease, with uncertain edges.
    detail = np.zeros_like(coarse)
    detail[495:510, 300:900] = 0.3  # Fine-scale edges retain parallel cracks.
    detail[500:503, 300:900] = 0.95
    detail[495:510, 600:602] = 0  # Small scale-dependent gaps are expected.
    detail[100:900, 100:110] = 0.1
    detail[100:900, 950:960] = 0.95  # Fine-scale-only texture cannot seed a repair.
    mask = repair_mask(coarse, confirmation=detail)
    assert not mask[:, :200].any()
    assert mask[495:510, 300:900].all()
    assert not mask[:, 940:].any()


@pytest.mark.parametrize("size", [512, 1024, 2048])
def test_confirmed_crease_cannot_extend_into_unsupported_face_detail(size):
    coarse = np.zeros((size, size), dtype=np.float32)
    detail = np.zeros_like(coarse)
    pixel = size // 256
    x, y = size // 2, size // 2
    top, bottom = size // 8, size * 7 // 8
    coarse[top:bottom, x : x + 2 * pixel] = 0.95
    # A long confirmed crease has a locally false confident branch over a face.
    coarse[y : y + 10 * pixel, x : x + 12 * pixel] = 0.95
    coarse[top:bottom, x - 3 * pixel : x] = 0.3
    detail[top:bottom, x : x + 2 * pixel] = 0.95
    detail[top:bottom, x - pixel : x] = 0.3
    # Nearby fine-only texture cannot start its own repair.
    detail[top:bottom, x + 20 * pixel : x + 22 * pixel] = 0.95

    mask = repair_mask(coarse, confirmation=detail)

    assert mask[top:bottom, x - pixel : x + 2 * pixel].all()
    assert not mask[:, x + 3 * pixel :].any()
    assert not mask[:, : x - 2 * pixel].any()


def test_confirmation_does_not_bridge_a_long_unsupported_stretch():
    coarse = np.zeros((1024, 1024), dtype=np.float32)
    coarse[500:503, 100:900] = 0.95
    detail = coarse.copy()
    detail[:, 450:550] = 0

    mask = repair_mask(coarse, confirmation=detail)

    assert mask[500:503, 100:450].all()
    assert mask[500:503, 550:900].all()
    assert not mask[:, 452:548].any()


def test_detector_requires_confirmation_before_repairing_a_bright_strand():
    shapes = []

    class Necklace(Detector):
        def run(self, _outputs, feeds):
            tensor = feeds["input"]
            shapes.append(tensor.shape)
            result = np.zeros_like(tensor)
            if tensor.shape[2] == 256:
                result[:, :, 80:250, 120:125] = 0.99
            return [result]

    image = np.zeros((512, 1024, 3), np.uint8)
    assert not learned_scratch_mask(Necklace(), image).any()
    assert shapes == [(1, 1, 256, 512), (1, 1, 512, 1024)]
