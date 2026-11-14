from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.retouch.catalog import CATALOG, specs_for
from app.retouch.corners import (
    blend_corner_fill,
    corner_context,
    light_corner_mask,
    normalize_edge_fade,
)
from app.retouch.engine import MissingWeights, OnnxRetoucher
from app.retouch.options import RetouchOptions, option_token, options_from_token
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed
from tests.test_retouch import MarkRetoucher


def damaged_photo():
    image = np.full((400, 600, 3), (110, 125, 135), np.uint8)
    cv2.fillConvexPoly(image, np.array([[0, 0], [17, 0], [0, 22]]), (235, 230, 220))
    image[180:200, 280:300] = 255  # An interior highlight is not corner damage.
    return image


@pytest.mark.parametrize("rotation", range(4))
@pytest.mark.parametrize("scale", [1, 3])
def test_corner_mask_tracks_rotation_and_scan_resolution(rotation, scale):
    image = np.rot90(damaged_photo(), rotation)
    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    mask = np.rot90(light_corner_mask(image), -rotation)
    assert mask[:5 * scale, :5 * scale].all()
    assert not mask[50 * scale:, 50 * scale:].any()
    assert mask.mean() < 0.005


def test_corner_mask_repairs_thin_worn_strip_but_not_detached_highlight():
    image = np.full((400, 600, 3), 100, np.uint8)
    image[0:8, 0:100] = 235
    image[25:32, 25:32] = 235
    mask = light_corner_mask(image)
    assert mask[:8, :100].all()
    assert not mask[25:32, 25:32].any()


@pytest.mark.parametrize("kind", ["flat", "sky", "snow", "colored", "tiny"])
def test_corner_mask_preserves_broad_bright_scenery(kind):
    image = np.full((400, 600, 3), 100, np.uint8)
    if kind == "flat":
        image[:] = 245
    elif kind == "sky":
        image[:] = np.linspace(245, 170, 400).astype(np.uint8)[:, None, None]
    elif kind == "snow":
        cv2.fillConvexPoly(image, np.array([[0, 0], [250, 0], [0, 200]]), (245, 245, 245))
    elif kind == "colored":
        image[:10, :10] = (255, 100, 100)
    else:
        image = image[:16, :16]
    assert not light_corner_mask(image).any()


def test_corner_step_requires_only_lama_and_no_duplicate_weights(tmp_path):
    flags = dict(upscale=False, denoise=False, faces=False, colorize=False, light_corners=True)
    assert [spec.id for spec in specs_for(**flags, scratches=False)] == ["inpaint"]
    assert [spec.id for spec in specs_for(**flags, scratches=True)] == [
        "scratch-detection", "inpaint"
    ]
    with pytest.raises(MissingWeights, match="lama.onnx"):
        OnnxRetoucher(tmp_path).apply(damaged_photo(), RetouchOptions(light_corners=True))


def test_corner_fill_preserves_unmasked_pixels_and_reports_progress(tmp_path, monkeypatch):
    (tmp_path / CATALOG["inpaint"].filename).touch()

    class Lama:
        def get_inputs(self):
            return [
                SimpleNamespace(name="image", shape=[1, 3, 512, 512]),
                SimpleNamespace(name="mask", shape=[1, 1, 512, 512]),
            ]

        def run(self, _outputs, feeds):
            return [np.full_like(feeds["image"], 125)]

    engine = OnnxRetoucher(tmp_path)
    monkeypatch.setattr(engine, "_session", lambda spec: Lama())
    progress, stages = [], []
    image = damaged_photo().astype(np.float32)
    image[100, 100] += 0.25
    result = engine.apply(image, RetouchOptions(light_corners=True), progress.append, stages.append)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result[:4, :4], 125, atol=0.001)
    np.testing.assert_array_equal(result[50:, 50:], image[50:, 50:])
    assert stages == [
        "Detecting light corner damage", "Repairing light corners", "Normalizing faded edges"
    ]
    assert progress == sorted(set(progress)) and progress[-1] == 99
    assert progress[0] < 99


def test_corner_step_runs_before_levels_and_is_optional(tmp_path, monkeypatch):
    from app.retouch import engine as engine_module

    engine = OnnxRetoucher(tmp_path)
    calls = []
    monkeypatch.setattr(engine, "_require", lambda options: None)

    def detect(image):
        calls.append("corners")
        return np.zeros(image.shape[:2], bool)

    def contrast(image):
        calls.append("contrast")
        return image

    monkeypatch.setattr(engine_module, "light_corner_mask", detect)
    monkeypatch.setattr(engine_module, "restore_contrast", contrast)
    image = damaged_photo()
    engine.apply(image, RetouchOptions(light_corners=True, contrast=True))
    assert calls == ["corners", "contrast"]
    calls.clear()
    np.testing.assert_array_equal(engine.apply(image, RetouchOptions()), image)
    assert not calls


def test_clean_photo_does_not_load_inpainting_session(tmp_path, monkeypatch):
    (tmp_path / CATALOG["inpaint"].filename).touch()
    engine = OnnxRetoucher(tmp_path)

    def unexpected_session(spec):
        pytest.fail("A clean photo should skip inpainting")

    monkeypatch.setattr(engine, "_session", unexpected_session)
    image = np.full((400, 600, 3), 220, np.uint8)
    progress = []
    result = engine.apply(image, RetouchOptions(light_corners=True), progress.append)
    np.testing.assert_array_equal(result, image)
    assert progress[-1] == 99


def test_corner_options_round_trip_and_preserve_old_tokens():
    for options in (RetouchOptions(light_corners=True),
                    RetouchOptions(light_corners=True, paper_mesh=True, dust=True)):
        assert options.any_selected()
        assert options_from_token(option_token(options)) == options
    old = options_from_token("u0d0f0c0s0b0t0")
    assert old is not None and not old.light_corners
    assert option_token(old) == "u0d0f0c0s0b0t0"


def test_corner_defaults_job_and_stale_result(client, app_bundle):
    app, services = app_bundle
    services.retoucher = MarkRetoucher()
    saved = client.put("/api/settings", json={"retouch_light_corners": True})
    assert saved.status_code == 200 and saved.json()["retouch_light_corners"]
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert region["retouch_light_corners"]
    url = f'/api/scans/{scan_id}/regions/{region["id"]}'
    assert client.post(url + "/retouch", json={"light_corners": True}).status_code == 202
    app.state.worker.process_available()
    ready = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert ready["retouch_ready"]
    assert "|corners-v3|" in ready["retouch_signature"]
    changed = client.patch(url, json={"retouch_light_corners": False})
    assert changed.json()["retouch_status"] == "stale"
    assert client.get("/api/statistics").json()["retouched_light_corners"] == 1


def test_bulk_corner_repair_checks_lama(client, app_bundle):
    _, services = app_bundle
    response = client.post("/api/retouch/bulk", json={"choice": {"light_corners": True}})
    assert response.status_code == 400 and "lama.onnx" in response.json()["detail"]
    directory: Path = services.settings.resolved_models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CATALOG["inpaint"].filename).touch()
    response = client.post("/api/retouch/bulk", json={"choice": {"light_corners": True}})
    assert response.status_code == 202


@pytest.mark.parametrize("rotation", range(4))
def test_edge_mask_covers_scanner_frame_and_long_bright_strip(rotation):
    image = np.full((400, 600, 3), 120, np.uint8)
    image[:, :3] = 20
    image[200:, 3:9] = 230
    mask = np.rot90(light_corner_mask(np.rot90(image, rotation)), -rotation)
    assert mask[:, :3].all()
    assert mask[220:390, :9].all()
    assert not mask[:, 20:].any()


def test_inpainting_context_mirrors_holes_as_well_as_pixels():
    image = damaged_photo().astype(np.float32)
    mask = light_corner_mask(image)
    context, holes, pad = corner_context(image, mask)
    np.testing.assert_array_equal(context[pad:-pad, pad:-pad], image)
    np.testing.assert_array_equal(holes[pad:-pad, pad:-pad], mask)
    assert holes[pad - 1, pad - 1]
    assert holes[pad, pad - 1]
    assert holes[pad - 1, pad]


def test_large_scan_fill_uses_wide_context_and_preserves_source_detail():
    image = np.full((1800, 2400, 3), 120.25, np.float32)
    mask = np.zeros(image.shape[:2], bool)
    mask[:40, :40] = True
    image[mask] = 240
    context, holes, pad = corner_context(image, mask)
    assert max(context.shape[:2]) == 1536 + 2 * pad
    assert holes[pad:pad + 20, pad:pad + 20].all()
    filled = np.full_like(context[pad:-pad, pad:-pad], 120)
    result = blend_corner_fill(image, filled, mask)
    assert result.shape == image.shape and result.dtype == np.float32
    np.testing.assert_array_equal(result[mask], 120)
    np.testing.assert_array_equal(result[100:, 100:], image[100:, 100:])


def test_previous_corner_revision_is_stale():
    from app.models import Region
    from app.retouch.options import expected_retouch_signature, retouch_matches

    region = Region(center_x=100, center_y=100, width=200, height=200,
                    angle_deg=0, quarter_turns=0, retouch_light_corners=True,
                    retouch_path="retouch/example.png")
    signature = expected_retouch_signature(region)
    region.retouch_signature = signature.replace("corners-v3", "corners-v2")
    assert not retouch_matches(region)
    region.retouch_signature = signature
    assert retouch_matches(region)


@pytest.mark.parametrize("rotation", range(4))
def test_edge_fade_reduces_veil_and_preserves_detail(rotation):
    y, x = np.indices((400, 600))
    texture = 2 * np.sin(y / 3) + 2 * np.sin(x / 3)
    clean = np.repeat((120 + texture)[..., None], 3, axis=2).astype(np.float32)
    faded = clean + (30 * np.exp(-x / 20))[..., None].astype(np.float32)
    result = np.rot90(normalize_edge_fade(np.rot90(faded, rotation)), -rotation)
    assert np.mean(np.abs(result[:, :30] - clean[:, :30])) < np.mean(
        np.abs(faded[:, :30] - clean[:, :30])
    ) * 0.55
    # Interior content and the fine texture are retained, with no row seams.
    np.testing.assert_array_equal(result[150:250, 200:400], faded[150:250, 200:400])
    np.testing.assert_allclose(np.diff(result[100:200, 10, 0]),
                               np.diff(clean[100:200, 10, 0]), atol=0.1)


@pytest.mark.parametrize("kind", ["flat", "gradient", "snow"])
def test_normalization_leaves_broad_scene_highlights_alone(kind):
    image = np.full((400, 600, 3), 230, np.float32)
    if kind == "gradient":
        image[:] = np.linspace(240, 100, 600)[None, :, None]
    elif kind == "snow":
        image[:] = 100
        cv2.fillConvexPoly(image, np.array([[0, 0], [250, 0], [0, 200]]), (245, 245, 245))
    np.testing.assert_array_equal(normalize_edge_fade(image), image)


def test_red_faded_edge_correction_is_bounded_and_requires_persistent_cast():
    y, x = np.indices((400, 600))
    texture = 8 * np.sin(y / 15) + 4 * np.sin(x / 15)
    clean = np.array([180, 125, 115], np.float32) + texture[..., None]
    veil = np.exp(-(599 - x) / 60)[..., None] * np.array([0, 22, 25])
    faded = (clean + veil).astype(np.float32)
    result = normalize_edge_fade(faded)
    assert np.mean(np.abs(result[:, -40:, 1:] - clean[:, -40:, 1:])) < np.mean(
        np.abs(faded[:, -40:, 1:] - clean[:, -40:, 1:])
    ) * 0.75
    np.testing.assert_array_equal(result[150:250, 200:350], faded[150:250, 200:350])
    assert np.max(faded - result) <= 40


def test_extreme_aspect_ratio_skips_underresolved_edge_estimates():
    image = np.full((64, 5000, 3), 200, np.uint8)
    assert not light_corner_mask(image).any()
    np.testing.assert_array_equal(normalize_edge_fade(image), image)


@pytest.mark.parametrize("rotation", range(4))
@pytest.mark.parametrize("scale", [1, 3])
def test_bright_strip_can_widen_locally_and_stops_before_disconnected_highlight(rotation, scale):
    image = np.full((400, 600, 3), 120, np.uint8)
    for y in range(400):
        width = 5 + round(18 * y / 399)
        image[y, :width] = 230
    image[240:350, 34:42] = 235  # Scene detail after a clean gap.
    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    mask = np.rot90(light_corner_mask(np.rot90(image, rotation)), -rotation)
    assert mask[320 * scale:390 * scale, :19 * scale].all()
    assert not mask[250 * scale:340 * scale, 34 * scale:42 * scale].any()
    assert not mask[:, 32 * scale:].any()


@pytest.mark.parametrize("rotation", range(4))
def test_faint_narrow_edge_is_normalized_without_changing_scene_texture(rotation):
    y, x = np.indices((400, 600))
    clean = np.repeat((150 + 2 * np.sin(y / 3))[..., None], 3, axis=2).astype(np.float32)
    faded = clean + (14 * np.exp(-x / 4))[..., None].astype(np.float32)
    result = np.rot90(normalize_edge_fade(np.rot90(faded, rotation)), -rotation)
    assert np.mean(result[:, :5] - clean[:, :5]) < np.mean(faded[:, :5] - clean[:, :5]) * 0.6
    np.testing.assert_allclose(np.diff(result[100:200, 3, 0]),
                               np.diff(clean[100:200, 3, 0]), atol=0.1)
    np.testing.assert_array_equal(result[150:250, 200:400], faded[150:250, 200:400])


@pytest.mark.parametrize("rotation", range(4))
def test_pale_strip_with_unequal_channel_fading_requires_sustained_support(rotation):
    image = np.full((400, 600, 3), (180, 160, 150), np.uint8)
    image[:240, :6] = (200, 167, 149)
    mask = np.rot90(light_corner_mask(np.rot90(image, rotation)), -rotation)
    assert mask[20:200, :6].all()
    assert not mask[300:, 20:].any()
    # The same color appearing briefly at an edge is insufficient evidence.
    image[:] = (180, 160, 150)
    image[150:180, :6] = (200, 167, 149)
    assert not light_corner_mask(np.rot90(image, rotation)).any()


def test_pale_strip_bridges_only_bounded_gaps_between_confirmed_segments():
    image = np.full((400, 600, 3), (180, 160, 150), np.uint8)
    image[20:110, :6] = (200, 167, 149)
    image[150:260, :6] = (200, 167, 149)
    mask = light_corner_mask(image)
    assert mask[70:220, :6].all()
    assert not mask[320:, :6].any()
