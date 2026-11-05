import hashlib
import sqlite3
import threading
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from alembic.config import Config
from PIL import Image

from alembic import command
from app.clock import utcnow
from app.imaging.crop import crop_signature, upright_crop
from app.imaging.io import load_rgb
from app.models import Job, Region, Setting
from app.retouch.catalog import CATALOG, ExtraFile
from app.retouch.engine import MissingWeights, OnnxRetoucher, _Budget, _run_upscale_tile
from app.retouch.fetch import (
    FetchError,
    _hash,
    download,
    inspect_file,
    install_archive,
    model_actions,
    prepare_download,
    progress_for,
)
from app.retouch.imageops import (
    FACE_TEMPLATE,
    apply_ab,
    chroma_collapsed,
    colorizer_tone,
    masked_tile_count,
    masked_tiles,
    paste_face,
    square_tile_count,
    tame_ab,
    tiled_map,
    warp_face,
)
from app.retouch.options import (
    RetouchOptions,
    flags_restore_faces,
    options_from_token,
    retouch_is_current,
)
from app.retouch.progress import (
    clear_retouch_progress,
    retouch_progress,
    retouch_stage,
    set_retouch_progress,
    set_retouch_stage,
)
from app.retouch.scratch import scratch_mask
from app.retouch.session import execution_providers
from tests.synthetic import encode_png, make_bed
from tests.test_api import RecordingImmich, _import_bed

_YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


class MarkRetoucher:
    def apply(
        self,
        image: np.ndarray,
        options: RetouchOptions,
        on_progress=None,
        on_stage=None,
    ) -> np.ndarray:
        out = np.array(image, copy=True)
        if options.denoise and not options.upscale:
            out[:12, :12] = (0, 0, 255)
        else:
            out[:12, :12] = (255, 0, 0)
        if options.faces:
            out[:12, -12:] = (0, 255, 0)
        if options.upscale:
            out = np.repeat(np.repeat(out, 2, axis=0), 2, axis=1)
        return out


def test_tiles_match_nearest_upscale_and_keep_a_flat_field() -> None:
    image = np.arange(180 * 300, dtype=np.uint8).reshape(180, 300)
    image = np.stack([image, image, np.flipud(image)], axis=-1)

    def double(tile: np.ndarray) -> np.ndarray:
        return np.repeat(np.repeat(tile, 2, axis=0), 2, axis=1)

    scaled = tiled_map(image, double, tile=64, overlap=0)
    assert scaled.shape == (360, 600, 3)
    assert np.array_equal(scaled, double(image))

    flat = np.full((90, 70, 3), 40, dtype=np.uint8)
    assert np.array_equal(tiled_map(flat, lambda tile: tile, tile=32, overlap=8), flat)

    small = np.full((10, 12, 3), 7, dtype=np.uint8)
    enlarged = tiled_map(small, double, tile=32, overlap=4)
    assert enlarged.shape == (20, 24, 3)
    assert np.all(enlarged == 7)


def test_overlapping_rows_stitch_exactly() -> None:
    rng = np.random.default_rng(3)
    image = rng.integers(0, 256, size=(150, 170, 3), dtype=np.uint8)

    def double(tile: np.ndarray) -> np.ndarray:
        return np.repeat(np.repeat(tile, 2, axis=0), 2, axis=1)

    assert np.array_equal(tiled_map(image, double, tile=48, overlap=12), double(image))


def test_lama_gets_a_full_mask_at_full_resolution(tmp_path) -> None:
    seen: list[tuple[tuple[int, ...], float]] = []

    class Input:
        def __init__(self, name: str, channels: int) -> None:
            self.name = name
            self.shape = [1, channels, 512, 512]

    class Lama:
        def get_inputs(self):
            return [Input("image", 3), Input("mask", 1)]

        def run(self, _outputs, feeds):
            seen.append((feeds["image"].shape, float(feeds["mask"].max())))
            return [np.full((1, 3, 512, 512), 200.0, dtype=np.float32)]

    retoucher = OnnxRetoucher(tmp_path)
    retoucher._session = lambda _spec: Lama()  # type: ignore[method-assign]
    image = np.full((700, 1400, 3), 90, dtype=np.uint8)
    mask = np.zeros(image.shape[:2], dtype=bool)
    mask[100:110, 50:60] = True
    filled = retoucher._inpaint(image, mask)
    assert seen == [((1, 3, 512, 512), 1.0)]
    assert filled[105, 55, 0] == 200
    assert filled[600, 1300, 0] == 90

    hits: list[np.ndarray] = []

    def mark(tile: np.ndarray, tile_mask: np.ndarray) -> np.ndarray:
        hits.append(tile_mask)
        return np.full_like(tile, 7)

    wide = np.zeros(image.shape[:2], dtype=bool)
    wide[:, 300] = True
    out = masked_tiles(image, wide, mark, tile_h=512, tile_w=512, overlap=64)
    assert all(hit.max() == 1 for hit in hits)
    assert np.all(out[:, 300] == 7)
    assert np.all(out[:, 299] == 90)


def test_upscale_output_overshoot_is_clipped_not_rescaled() -> None:
    class Input:
        name = "input"
        shape = [1, 3, 8, 8]

    class Upscaler:
        def get_inputs(self):
            return [Input()]

        def run(self, _outputs, feeds):
            out = np.repeat(np.repeat(feeds["input"], 2, axis=2), 2, axis=3)
            out[:, :, 0, 0] = -0.3
            return [out]

    tile = np.full((8, 8, 3), 128, dtype=np.uint8)
    result = _run_upscale_tile(Upscaler(), tile)
    assert result[0, 0, 0] == 0
    assert result[5, 5, 0] == 128


def test_tile_progress_counts_every_inference() -> None:
    image = np.zeros((20, 24, 3), dtype=np.uint8)
    calls = 0
    steps = 0

    def run(tile: np.ndarray) -> np.ndarray:
        nonlocal calls
        calls += 1
        return np.repeat(np.repeat(tile, 2, axis=0), 2, axis=1)

    def count() -> None:
        nonlocal steps
        steps += 1

    tiled_map(image, run, tile=8, overlap=1, on_tile=count)
    assert steps == calls == square_tile_count(20, 24, 8, 1)
    assert steps > 1

    mask = np.zeros((700, 1400), dtype=bool)
    mask[:, 300] = True
    filled_steps = [0]
    masked_tiles(
        np.zeros((700, 1400, 3), dtype=np.uint8),
        mask,
        lambda tile, _mask: tile,
        tile_h=512,
        tile_w=512,
        overlap=64,
        on_tile=lambda: filled_steps.__setitem__(0, filled_steps[0] + 1),
    )
    assert filled_steps[0] == masked_tile_count(mask, 512, 512, 64)
    assert filled_steps[0] > 0


def test_retouch_progress_is_stored_clamped_and_cleared() -> None:
    region_id = "progress-region"
    clear_retouch_progress(region_id)
    try:
        assert retouch_progress(region_id) is None
        set_retouch_progress(region_id, 40)
        assert retouch_progress(region_id) == 40
        set_retouch_progress(region_id, 140)
        assert retouch_progress(region_id) == 100
        clear_retouch_progress(region_id)
        assert retouch_progress(region_id) is None
        set_retouch_progress(region_id, 0)
        assert retouch_progress(region_id) == 0
    finally:
        clear_retouch_progress(region_id)


def test_budget_holds_its_percent_when_more_faces_turn_up() -> None:
    seen: list[int] = []
    budget = _Budget(10, 1, seen.append)
    budget.add(6)
    budget.note_faces(4)
    budget.add(1)
    budget.finish()
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))
    assert seen[-1] == 99


def test_upscale_reports_a_rising_percent(tmp_path, monkeypatch) -> None:
    (tmp_path / CATALOG["scale"].filename).write_bytes(b"onnx")

    class Input:
        name = "input"
        shape = [1, 3, 8, 8]

    class Upscaler:
        def get_inputs(self):
            return [Input()]

        def run(self, _outputs, feeds):
            return [np.repeat(np.repeat(feeds["input"], 2, axis=2), 2, axis=3)]

    monkeypatch.setattr("app.retouch.engine.open_session", lambda *_args: Upscaler())
    seen: list[int] = []
    image = np.full((20, 24, 3), 40, dtype=np.uint8)
    OnnxRetoucher(tmp_path).apply(image, RetouchOptions(upscale=True), on_progress=seen.append)
    assert seen[0] > 0
    assert seen[-1] == 99
    assert seen == sorted(seen)
    assert len(seen) == square_tile_count(20, 24, 8, 1)


def test_scale_and_denoise_each_run_once_and_keep_their_size(tmp_path, monkeypatch) -> None:
    opened: list[str] = []
    calls = {"n": 0}

    class Input:
        def __init__(self, name: str) -> None:
            self.name = name
            self.shape = [1, 3, 8, 8]

    class Net:
        def __init__(self, second: bool = False) -> None:
            self.second = second
            self.strengths: list[float] = []

        def get_inputs(self):
            inputs = [Input("image")]
            if self.second:
                inputs.append(Input("denoise"))
            return inputs

        def run(self, _outputs, feeds):
            calls["n"] += 1
            if self.second:
                self.strengths.append(float(feeds["denoise"]))
            lifted = np.clip(feeds["image"] + 0.2, 0, 1)
            return [np.repeat(np.repeat(lifted, 2, axis=2), 2, axis=3)]

    net = Net()
    monkeypatch.setattr(
        "app.retouch.engine.open_session",
        lambda path, _execution, _device: opened.append(Path(path).name) or net,
    )
    image = np.full((20, 24, 3), 40, dtype=np.uint8)
    tiles = square_tile_count(20, 24, 8, 1)
    retoucher = OnnxRetoucher(tmp_path)

    untouched = retoucher.apply(image, RetouchOptions())
    assert np.array_equal(untouched, image)
    assert opened == []
    assert calls["n"] == 0

    def run(options: RetouchOptions, filename: str) -> tuple[np.ndarray, list[str]]:
        for spec in (CATALOG["upscale"], CATALOG["scale"]):
            (tmp_path / spec.filename).unlink(missing_ok=True)
        (tmp_path / filename).write_bytes(b"onnx")
        retoucher._sessions.clear()
        opened.clear()
        calls["n"] = 0
        stages: list[str] = []
        result = retoucher.apply(image, options, on_stage=stages.append)
        return result, stages

    denoised, denoise_stages = run(RetouchOptions(denoise=True), CATALOG["upscale"].filename)
    assert denoise_stages == ["Denoising"]
    assert opened == [CATALOG["upscale"].filename]
    assert calls["n"] == tiles
    assert denoised.shape == image.shape
    assert np.all(denoised == 91)

    scaled, scale_stages = run(RetouchOptions(upscale=True), CATALOG["scale"].filename)
    assert scale_stages == ["Upscaling"]
    assert opened == [CATALOG["scale"].filename]
    assert calls["n"] == tiles
    assert scaled.shape == (40, 48, 3)
    assert np.all(scaled == 91)

    both, both_stages = run(
        RetouchOptions(upscale=True, denoise=True),
        CATALOG["upscale"].filename,
    )
    assert both_stages == ["Upscaling and denoising"]
    assert opened == [CATALOG["upscale"].filename]
    assert calls["n"] == tiles
    assert both.shape == (40, 48, 3)
    assert np.all(both == 91)

    (tmp_path / CATALOG["upscale"].filename).write_bytes(b"onnx")
    (tmp_path / CATALOG["scale"].filename).write_bytes(b"onnx")
    retoucher._sessions.clear()
    net.second = True
    calls["n"] = 0
    retoucher.apply(image, RetouchOptions(denoise=True))
    assert net.strengths
    assert set(net.strengths) == {1.0}
    net.strengths.clear()
    retoucher.apply(image, RetouchOptions(upscale=True))
    assert set(net.strengths) == {0.0}


def test_a_changed_model_file_opens_a_new_session(tmp_path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        "app.retouch.engine.open_session",
        lambda path, _execution, _device: opened.append(path.name) or object(),
    )
    spec = CATALOG["upscale"]
    path = tmp_path / spec.filename
    path.write_bytes(b"one")
    retoucher = OnnxRetoucher(tmp_path)
    first = retoucher._session(spec)
    assert retoucher._session(spec) is first
    path.write_bytes(b"second version")
    assert retoucher._session(spec) is not first
    assert opened == [spec.filename, spec.filename]


def test_missing_companion_file_is_reported(tmp_path) -> None:
    (tmp_path / CATALOG["colorize"].filename).write_bytes(b"onnx")
    with pytest.raises(MissingWeights, match="ddcolor.data"):
        OnnxRetoucher(tmp_path)._require(RetouchOptions(colorize=True))


def test_the_hash_is_reused_until_the_file_changes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "weights.onnx"
    path.write_bytes(b"one")
    assert _hash(path) == hashlib.sha256(b"one").hexdigest()
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("hashed again"))
    assert _hash(path) == hashlib.sha256(b"one").hexdigest()
    monkeypatch.undo()
    path.write_bytes(b"second version")
    assert _hash(path) == hashlib.sha256(b"second version").hexdigest()


def test_a_job_that_keeps_crashing_the_server_fails(app_bundle) -> None:
    app, services = app_bundle
    with services.session_factory() as session:
        for job_id, attempts in (("job-again", 1), ("job-spent", 3)):
            session.add(
                Job(
                    id=job_id,
                    type="detect",
                    status="running",
                    scan_id=None,
                    region_id=None,
                    payload="{}",
                    error=None,
                    attempts=attempts,
                    created_at=utcnow(),
                    started_at=utcnow(),
                    finished_at=None,
                )
            )
        session.commit()
    assert app.state.worker.recover() == 1
    with services.session_factory() as session:
        assert session.get(Job, "job-again").status == "queued"
        spent = session.get(Job, "job-spent")
        assert spent.status == "failed"
        assert "3 attempts" in spent.error


def test_neutral_chroma_stays_gray_and_a_shift_changes_it() -> None:
    gray = np.full((16, 16, 3), 80, dtype=np.uint8)
    neutral = apply_ab(gray, np.zeros((8, 8, 2), dtype=np.float32))
    assert np.max(np.abs(neutral.astype(np.int16) - 80)) <= 1
    # DDColor returns a and b in Lab units. A small value is a faint tint, not a full one.
    faint = apply_ab(gray, np.full((16, 16, 2), 0.8, dtype=np.float32))
    assert np.max(np.abs(faint.astype(np.int16) - 80)) <= 3
    warm = apply_ab(gray, np.full((16, 16, 2), 30.0, dtype=np.float32))
    assert int(warm[8, 8, 0]) > int(warm[8, 8, 2]) + 30


def test_a_collapsed_colorizer_spike_does_not_bleed() -> None:
    ab = np.zeros((32, 32, 2), dtype=np.float32)
    ab[4:8, 2:6] = (420.0, -390.0)
    assert chroma_collapsed(ab)
    gray = np.full((64, 80, 3), 140, dtype=np.uint8)
    painted = apply_ab(gray, tame_ab(ab))
    assert np.max(np.abs(painted.astype(np.int16) - 140)) <= 1
    healthy = np.full((16, 16, 2), 30.0, dtype=np.float32)
    assert not chroma_collapsed(healthy)
    assert np.allclose(tame_ab(healthy), 30.0)


def test_colorizer_tone_pulls_a_high_key_scan_down_and_keeps_order() -> None:
    image = np.full((40, 40, 3), 210, dtype=np.uint8)
    image[10:30, 10:30] = 120
    toned = colorizer_tone(image)
    assert abs(int(np.median(toned[:, :, 0])) - 92) <= 2
    assert int(toned[20, 20, 0]) < int(toned[0, 0, 0])


def test_a_collapsed_colorizer_is_run_again_on_a_toned_input(tmp_path) -> None:
    class Input:
        name = "image"
        shape = [1, 3, 256, 256]

    class Colorizer:
        def __init__(self) -> None:
            self.calls = 0
            self.means: list[float] = []

        def get_inputs(self):
            return [Input()]

        def run(self, _outputs, feeds):
            self.calls += 1
            self.means.append(float(feeds["image"].mean()))
            if self.calls == 1:
                blown = np.zeros((1, 2, 256, 256), dtype=np.float32)
                blown[0, :, 0:8, 0:8] = 400
                return [blown]
            ab = np.full((1, 2, 256, 256), 25.0, dtype=np.float32)
            return [ab]

    model = Colorizer()
    retoucher = OnnxRetoucher(tmp_path)
    retoucher._session = lambda _spec: model  # type: ignore[method-assign]
    gray = np.full((48, 48, 3), 200, dtype=np.uint8)
    colored = retoucher._colorize(gray)
    assert model.calls == 2
    assert model.means[1] < model.means[0]
    assert int(colored[24, 24, 0]) > int(colored[24, 24, 2]) + 20

    healthy = Colorizer()

    def ready(_outputs, feeds):
        healthy.calls += 1
        return [np.full((1, 2, 256, 256), 20.0, dtype=np.float32)]

    healthy.run = ready  # type: ignore[method-assign]
    retoucher._session = lambda _spec: healthy  # type: ignore[method-assign]
    retoucher._colorize(gray)
    assert healthy.calls == 1


def test_scratch_mask_keeps_thin_strokes_and_ignores_a_filled_area() -> None:
    image = np.full((180, 180, 3), 120, dtype=np.uint8)
    image[:, 40:41] = 255
    image[70:110, 70:110] = 255
    mask = scratch_mask(image)
    assert mask[:, 40].any()
    assert not mask[90, 90]
    assert mask[70:110, 70:110].mean() < 0.15
    assert not scratch_mask(np.full_like(image, 30)).any()


def test_scratch_mask_keeps_a_wavy_crease_and_a_fade_between_strong_ends() -> None:
    image = np.full((220, 520, 3), 80, dtype=np.uint8)
    for x in range(520):
        y = int(70 + 10 * np.sin(x / 28))
        image[y - 1 : y + 2, x] = 220
    mask = scratch_mask(image)
    assert mask[70, 260]
    assert int(mask[40:110].sum()) > 400

    faded = np.full((200, 480, 3), 80, dtype=np.uint8)
    faded[96:101, 20:200] = 210
    faded[94:106, 200:236] = 98
    faded[96:101, 236:460] = 210
    faded[20:70, 20:70] = 240
    joined = scratch_mask(faded)
    assert joined[98, 80]
    assert joined[98, 400]
    assert joined[100, 218]
    assert not joined[45, 45]


def test_scratch_mask_bridges_a_fade_in_a_vertical_crease() -> None:
    faded = np.full((480, 200, 3), 80, dtype=np.uint8)
    faded[20:200, 96:101] = 210
    faded[200:236, 94:106] = 98
    faded[236:460, 96:101] = 210
    faded[20:70, 20:70] = 240
    joined = scratch_mask(faded)
    assert joined[80, 98]
    assert joined[400, 98]
    assert joined[218, 100]
    assert not joined[45, 45]


def test_scratch_mask_does_not_join_parallel_vertical_scratches_sideways() -> None:
    image = np.full((240, 240, 3), 80, dtype=np.uint8)
    image[20:220, 99:101] = 210
    image[20:220, 139:141] = 210
    image[119:121, 101:139] = 100
    mask = scratch_mask(image)
    assert mask[120, 100]
    assert mask[120, 140]
    assert not mask[120, 120]


def test_scratch_mask_leaves_a_blob_beside_a_tear() -> None:
    image = np.full((180, 240, 3), 70, dtype=np.uint8)
    image[78:98, 20:220] = 108
    image[86:90, 20:220] = 190
    image[100:118, 110:128] = 15
    mask = scratch_mask(image)
    assert mask[88, 120]
    assert mask[96, 120]
    assert mask[100:118, 110:128].mean() < 0.05


def test_scratch_mask_follows_a_diagonal_tear_past_a_break() -> None:
    image = np.full((180, 180, 3), 70, dtype=np.uint8)
    for step in range(55):
        y, x = 20 + step, 130 - step
        image[y : y + 2, x : x + 2] = 210
    for step in range(14):
        y, x = 88 + step, 62 - step
        image[y : y + 4, x : x + 3] = 200
    mask = scratch_mask(image)
    assert mask[22, 128]
    assert mask[94, 56]
    assert not mask[10, 10]


def test_scratch_mask_covers_the_shoulder_of_a_wide_tear() -> None:
    image = np.full((180, 240, 3), 70, dtype=np.uint8)
    image[78:98, 20:220] = 108
    image[86:90, 20:220] = 190
    image[20:55, 20:55] = 230
    mask = scratch_mask(image)
    assert mask[88, 120]
    assert mask[80, 120]
    assert mask[96, 120]
    assert not mask[40, 40]
    assert not mask[10, 10]


def test_identity_face_alignment_changes_only_the_interior() -> None:
    image = np.full((512, 512, 3), (10, 20, 30), dtype=np.uint8)
    warped = warp_face(image, FACE_TEMPLATE)
    assert warped is not None
    _aligned, matrix = warped
    same = paste_face(image, matrix, image)
    assert np.max(np.abs(same.astype(np.int16) - image.astype(np.int16))) <= 1
    restored = np.full_like(image, (255, 0, 0))
    pasted = paste_face(image, matrix, restored)
    assert pasted[256, 280, 0] > 200
    assert np.array_equal(pasted[0, 0], image[0, 0])


def test_cpu_is_the_provider_and_openvino_is_explicit() -> None:
    assert execution_providers("cpu", "CPU_FP32") == ["CPUExecutionProvider"]
    import onnxruntime as ort

    if "OpenVINOExecutionProvider" in ort.get_available_providers():
        providers = execution_providers("openvino", "CPU_FP32")
        assert providers[0][0] == "OpenVINOExecutionProvider"
        return
    with pytest.raises(RuntimeError, match="OpenVINO"):
        execution_providers("openvino", "CPU_FP32")


def test_only_an_accepted_license_can_download() -> None:
    assert CATALOG["face-detection"].sha256 == _YUNET_SHA256
    assert "codeformer" not in CATALOG
    assert all(spec.download_url and spec.sha256 for spec in CATALOG.values())
    with pytest.raises(FetchError, match="BSD-3-Clause"):
        prepare_download(CATALOG["upscale"], accepted=set())
    url = prepare_download(CATALOG["upscale"], accepted={"upscale"})
    assert url == CATALOG["upscale"].download_url
    with pytest.raises(FetchError, match="face-detection"):
        prepare_download(CATALOG["face-detection"], accepted=set())
    yunet = prepare_download(CATALOG["face-detection"], accepted={"face-detection"})
    assert yunet == CATALOG["face-detection"].download_url


def test_download_update_and_redownload_follow_the_file_on_disk(tmp_path) -> None:
    yunet = CATALOG["face-detection"]
    missing = inspect_file(yunet, tmp_path)
    assert model_actions(yunet, missing) == (True, False, False)
    offline = replace(yunet, download_url=None)
    assert model_actions(offline, missing) == (False, False, False)
    path = tmp_path / yunet.filename
    content = b"weights"
    path.write_bytes(content)
    assert model_actions(yunet, inspect_file(yunet, tmp_path)) == (False, True, False)
    pinned = replace(yunet, sha256=hashlib.sha256(content).hexdigest())
    assert inspect_file(pinned, tmp_path).matches_pin is True
    assert model_actions(pinned, inspect_file(pinned, tmp_path)) == (False, False, True)
    unpinned = replace(CATALOG["upscale"], sha256=None)
    (tmp_path / unpinned.filename).write_bytes(content)
    installed = inspect_file(unpinned, tmp_path)
    assert installed.present is True
    assert installed.matches_pin is None
    assert model_actions(unpinned, installed) == (False, False, True)


def test_a_zip_installs_the_onnx_and_its_weights(tmp_path) -> None:
    onnx = b"onnx-bytes"
    weights = b"weight-bytes"
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("inner/ddcolor.onnx", onnx)
        archive.writestr("inner/ddcolor.data", weights)
    spec = replace(
        CATALOG["colorize"],
        sha256=hashlib.sha256(onnx).hexdigest(),
        archive_name="inner/ddcolor.onnx",
        extra=(
            ExtraFile(
                filename="ddcolor.data",
                sha256=hashlib.sha256(weights).hexdigest(),
                archive_name="inner/ddcolor.data",
            ),
        ),
    )
    destination = tmp_path / "models" / spec.filename
    destination.parent.mkdir()
    install_archive(spec, archive_path, destination)
    assert destination.read_bytes() == onnx
    assert (destination.parent / "ddcolor.data").read_bytes() == weights
    assert inspect_file(spec, destination.parent).matches_pin is True

    broken = replace(spec, sha256="0" * 64)
    rejected = tmp_path / "rejected" / spec.filename
    rejected.parent.mkdir()
    with pytest.raises(FetchError, match="checksum"):
        install_archive(broken, archive_path, rejected)
    assert not rejected.exists()
    assert destination.read_bytes() == onnx


def test_a_zip_download_extracts_without_replacing_the_archive(tmp_path, monkeypatch) -> None:
    onnx = b"onnx-bytes"
    weights = b"weight-bytes" * 50
    payload = bytearray()
    with zipfile.ZipFile(tmp_path / "bundle.zip", "w") as archive:
        archive.writestr("inner/ddcolor.onnx", onnx)
        archive.writestr("inner/ddcolor.data", weights)
    payload.extend((tmp_path / "bundle.zip").read_bytes())

    class Response:
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield bytes(payload)

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr("app.retouch.fetch.httpx.stream", lambda *args, **kwargs: Response())
    spec = replace(
        CATALOG["colorize"],
        sha256=hashlib.sha256(onnx).hexdigest(),
        archive_name="inner/ddcolor.onnx",
        extra=(
            ExtraFile(
                filename="ddcolor.data",
                sha256=hashlib.sha256(weights).hexdigest(),
                archive_name="inner/ddcolor.data",
            ),
        ),
    )
    destination = tmp_path / "models" / spec.filename
    download(spec, destination, accepted={"colorize"})
    assert destination.read_bytes() == onnx
    assert (destination.parent / "ddcolor.data").read_bytes() == weights
    assert not destination.with_name(destination.name + ".archive").exists()
    assert not destination.with_name(destination.name + ".part").exists()


class _Stream:
    def __init__(self, payload: bytes, *, pause: threading.Event | None = None) -> None:
        self.payload = payload
        self.pause = pause
        self.headers = {"content-length": str(len(payload))}

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        if self.pause is None:
            yield self.payload
            return
        yield self.payload[:4]
        assert self.pause.wait(5)
        yield self.payload[4:]

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_download_reports_bytes_and_keeps_a_good_file_when_the_new_one_fails(
    tmp_path, monkeypatch
) -> None:
    original = b"weights-v1"
    replacement = b"weights-v2-ok"
    spec = replace(
        CATALOG["upscale"],
        sha256=hashlib.sha256(original).hexdigest(),
        download_url="http://models.test/upscale.onnx",
    )
    destination = tmp_path / spec.filename
    destination.write_bytes(original)
    bodies = iter([b"corrupt-download", replacement])

    def stream(*args: object, **kwargs: object) -> _Stream:
        return _Stream(next(bodies))

    monkeypatch.setattr("app.retouch.fetch.httpx.stream", stream)
    download(spec, destination, accepted={"upscale"})
    assert destination.read_bytes() == original

    with pytest.raises(FetchError, match="checksum"):
        download(spec, destination, accepted={"upscale"}, force=True)
    assert destination.read_bytes() == original
    assert progress_for(spec.id) is None
    assert not destination.with_name(destination.name + ".part").exists()

    updated = replace(spec, sha256=hashlib.sha256(replacement).hexdigest())
    download(updated, destination, accepted={"upscale"}, force=True)
    assert destination.read_bytes() == replacement
    assert progress_for(spec.id) is None


def test_a_running_download_is_listed_with_its_progress(client, tmp_path, monkeypatch) -> None:
    payload = b"0123456789abcdef"
    spec = CATALOG["face-detection"]
    release = threading.Event()
    started = threading.Event()

    class Response(_Stream):
        def iter_bytes(self):
            yield self.payload[:4]
            started.set()
            assert self.pause is not None
            assert self.pause.wait(5)
            yield self.payload[4:]

    monkeypatch.setattr(
        "app.retouch.fetch.httpx.stream",
        lambda *args, **kwargs: Response(payload, pause=release),
    )
    error: list[BaseException] = []

    def run() -> None:
        try:
            download(spec, tmp_path / spec.filename, accepted={spec.id})
        except Exception as exc:  # the bytes are not the pinned file
            error.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(5)
    try:
        listed = client.get("/api/retouch/models")
        assert listed.status_code == 200
        face = next(item for item in listed.json() if item["id"] == spec.id)
        assert face["progress"] == {"received": 4, "total": len(payload), "phase": "downloading"}
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert error and isinstance(error[0], FetchError)
    assert progress_for(spec.id) is None
    done = client.get("/api/retouch/models").json()
    assert next(item for item in done if item["id"] == spec.id)["progress"] is None


def test_redownload_asks_for_the_file_again(client, monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def fake_download(spec, path, *, accepted, force=False) -> None:
        seen["force"] = force
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"yunet")

    monkeypatch.setattr("app.api.retouch.download", fake_download)
    saved = client.post("/api/retouch/models/face-detection", json={"accept": True, "force": True})
    assert saved.status_code == 200
    assert seen["force"] is True


def test_download_requires_the_license(client, app_bundle, monkeypatch) -> None:
    assert client.post("/api/retouch/models/missing", json={"accept": True}).status_code == 404
    refused = client.post("/api/retouch/models/face-detection", json={"accept": False})
    assert refused.status_code == 400
    assert "Apache-2.0" in refused.json()["detail"]

    def fake_download(spec, path, *, accepted, force=False) -> None:
        assert spec.id == "face-detection"
        assert accepted == {"face-detection"}
        assert force is False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"yunet")

    monkeypatch.setattr("app.api.retouch.download", fake_download)
    saved = client.post("/api/retouch/models/face-detection", json={"accept": True})
    assert saved.status_code == 200
    body = saved.json()
    assert body["present"] is True
    assert body["version"] == "2023mar"
    assert body["matches_pin"] is False
    assert body["can_update"] is True
    assert body["can_download"] is False
    assert body["can_redownload"] is False
    assert body["progress"] is None


def test_new_photos_start_with_the_saved_steps(client, app_bundle) -> None:
    saved = client.put(
        "/api/settings",
        json={
            "immich_base_url": "",
            "immich_api_key": "",
            "output_format": "jpeg",
            "jpeg_quality": 95,
            "default_album_id": "",
            "retouch_upscale": True,
            "retouch_colorize": True,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["retouch_upscale"] is True
    assert saved.json()["retouch_denoise"] is True
    assert saved.json()["retouch_faces"] is False
    assert saved.json()["retouch_scratches"] is False

    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    detected = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert detected["retouch_upscale"] is True
    assert detected["retouch_denoise"] is True
    assert detected["retouch_colorize"] is True
    assert detected["retouch_faces"] is False

    added = client.post(
        f"/api/scans/{scan_id}/regions",
        json={"center_x": 800, "center_y": 200, "width": 80, "height": 60, "angle_deg": 0},
    )
    assert added.status_code == 201
    assert added.json()["retouch_upscale"] is True
    assert added.json()["retouch_scratches"] is False


def test_retouch_keeps_the_crop_and_upload_uses_it_only_when_chosen(client, app_bundle) -> None:
    app, services = app_bundle
    services.retoucher = MarkRetoucher()
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    detail = client.get(f"/api/scans/{scan_id}").json()
    first, second = detail["regions"][0], detail["regions"][1]
    assert first["retouch_faces"] is False
    assert first["upload_source"] == "crop"
    assert first["retouch_ready"] is False
    assert first["retouch_progress"] is None
    refused = client.patch(
        f"/api/scans/{scan_id}/regions/{first['id']}",
        json={"upload_source": "retouch"},
    )
    assert refused.status_code == 409

    models = client.get("/api/retouch/models").json()
    assert {item["id"] for item in models} == set(CATALOG)
    assert all(item["present"] is False for item in models)
    yunet = next(item for item in models if item["id"] == "face-detection")
    assert yunet["automatic_download"] is True
    assert yunet["license_id"] == "Apache-2.0"
    assert yunet["version"] == "2023mar"
    assert yunet["can_download"] is True
    assert yunet["can_update"] is False
    assert yunet["can_redownload"] is False
    assert yunet["progress"] is None

    empty = client.post(
        f"/api/scans/{scan_id}/regions/{first['id']}/retouch",
        json={"upscale": False, "faces": False, "colorize": False, "scratches": False},
    )
    assert empty.status_code == 422

    started = client.post(
        f"/api/scans/{scan_id}/regions/{first['id']}/retouch",
        json={"upscale": True, "faces": False, "colorize": False, "scratches": False},
    )
    assert started.status_code == 202
    assert started.json()["region"]["retouch_upscale"] is True
    assert started.json()["region"]["retouch_denoise"] is True
    again = client.post(
        f"/api/scans/{scan_id}/regions/{first['id']}/retouch",
        json={"upscale": True, "faces": False, "colorize": False, "scratches": False},
    )
    assert again.json()["job_id"] == started.json()["job_id"]
    faces = client.post(
        f"/api/scans/{scan_id}/regions/{second['id']}/retouch",
        json={"upscale": False, "faces": True, "colorize": False, "scratches": False},
    )
    assert faces.status_code == 202
    assert app.state.worker.process_one() is True
    midway = [job for job in client.get("/api/jobs").json() if job["type"] == "retouch"]
    assert sorted(job["status"] for job in midway) == ["finished", "queued"]
    assert app.state.worker.process_available() == 1

    done = client.get(f"/api/scans/{scan_id}").json()
    upscaled = next(region for region in done["regions"] if region["id"] == first["id"])
    restored = next(region for region in done["regions"] if region["id"] == second["id"])
    assert upscaled["retouch_ready"] is True
    assert upscaled["retouch_version"]
    assert first["retouch_version"] is None
    assert upscaled["retouch_reconstructs_faces"] is False
    assert restored["retouch_reconstructs_faces"] is True
    _assert_crop_was_kept(services, scan_id, upscaled, scaled=True)
    _assert_crop_was_kept(services, scan_id, restored, scaled=False)

    preview = client.get(f"/api/scans/{scan_id}/regions/{first['id']}/retouch-preview")
    assert preview.status_code == 200
    assert preview.content.startswith(b"\xff\xd8")
    assert (
        client.get(
            f"/api/scans/{scan_id}/regions/{done['regions'][2]['id']}/retouch-preview"
        ).status_code
        == 404
    )

    gateway = RecordingImmich()
    services.build_gateway = lambda _url, _key: gateway
    client.put(
        "/api/settings",
        json={
            "immich_base_url": "http://immich.local:2283",
            "immich_api_key": "secret-key",
            "output_format": "png",
            "jpeg_quality": 95,
            "default_album_id": "",
        },
    )
    client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [first["id"]]})
    app.state.worker.process_available()
    original = _png(gateway.uploads[0].content)
    assert original.getpixel((0, 0)) != (255, 0, 0)

    chosen = client.patch(
        f"/api/scans/{scan_id}/regions/{first['id']}",
        json={"upload_source": "retouch"},
    )
    assert chosen.status_code == 200
    assert chosen.json()["upload_source"] == "retouch"
    client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [first["id"]]})
    app.state.worker.process_available()
    derivative = _png(gateway.uploads[1].content)
    assert derivative.size == (original.size[0] * 2, original.size[1] * 2)
    assert derivative.getpixel((0, 0)) == (255, 0, 0)
    stored_dpi = derivative.info.get("dpi")
    assert stored_dpi is not None
    assert round(stored_dpi[0]) == 600
    assert round(stored_dpi[1]) == 600

    rotated = client.post(f"/api/scans/{scan_id}/regions/{first['id']}/rotate")
    assert rotated.json()["retouch_status"] == "stale"
    assert rotated.json()["upload_source"] == "crop"
    assert rotated.json()["retouch_ready"] is False

    scan_dir = services.storage.root / "scans" / scan_id
    earlier = services.storage.absolute(_retouch_path(services, second["id"]))
    assert client.get(f"/api/scans/{scan_id}/regions/{second['id']}/retouch-preview").is_success
    client.post(
        f"/api/scans/{scan_id}/regions/{second['id']}/retouch",
        json={"upscale": False, "faces": True, "colorize": False, "scratches": False},
    )
    app.state.worker.process_available()
    later = services.storage.absolute(_retouch_path(services, second["id"]))
    assert later != earlier
    rerun = next(
        item
        for item in client.get(f"/api/scans/{scan_id}").json()["regions"]
        if item["id"] == second["id"]
    )
    assert rerun["retouch_version"] != restored["retouch_version"]
    assert later.is_file()
    assert not earlier.exists()
    assert len(list((scan_dir / "retouch-previews").glob(f"{second['id']}-*.jpg"))) == 1

    assert client.delete(f"/api/scans/{scan_id}/regions/{second['id']}").status_code == 204
    assert not later.exists()
    assert not (scan_dir / "crops" / f"{second['id']}.png").exists()
    assert not list(scan_dir.glob(f"*previews/{second['id']}-*.jpg"))


def test_missing_weights_fail_the_photo_and_leave_the_crop(client, app_bundle) -> None:
    app, services = app_bundle
    scan_id = _import_bed(services, encode_png(make_bed(speck=False)))
    app.state.worker.process_available()
    region = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    queued = client.post(
        f"/api/scans/{scan_id}/regions/{region['id']}/retouch",
        json={"upscale": True, "faces": False, "colorize": False, "scratches": False},
    )
    assert queued.status_code == 202
    app.state.worker.process_available()
    failed = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert failed["retouch_status"] == "failed"
    assert "realesr-general-x4v3.onnx" in failed["retouch_error"]
    assert "BSD-3-Clause" in failed["retouch_error"]
    assert failed["upload_source"] == "crop"
    crop = services.storage.root / "scans" / scan_id / "crops" / f"{region['id']}.png"
    retouch_dir = services.storage.root / "scans" / scan_id / "retouch"
    assert crop.is_file()
    assert not list(retouch_dir.glob(f"{region['id']}*"))

    with services.session_factory() as session:
        stored = session.get(Region, region["id"])
        assert stored is not None
        stored.upload_source = "retouch"
        stored.retouch_status = "stale"
        session.commit()
    gateway = RecordingImmich()
    services.build_gateway = lambda _url, _key: gateway
    client.put(
        "/api/settings",
        json={
            "immich_base_url": "http://immich.local:2283",
            "immich_api_key": "secret-key",
            "output_format": "png",
        },
    )
    client.post(f"/api/scans/{scan_id}/upload", json={"region_ids": [region["id"]]})
    app.state.worker.process_available()
    after = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert after["upload_status"] == "failed"
    assert "not ready" in after["upload_error"]
    assert gateway.uploads == []


def test_scale_denoise_both_and_neither_keep_their_dimensions(client, app_bundle) -> None:
    app, services = app_bundle
    services.retoucher = MarkRetoucher()
    scan_id = _import_bed(services, encode_png(make_bed()))
    assert app.state.worker.process_available() == 1
    region_id = client.get(f"/api/scans/{scan_id}").json()["regions"][0]["id"]
    url = f"/api/scans/{scan_id}/regions/{region_id}/retouch"

    neither = client.post(
        url,
        json={
            "upscale": False,
            "denoise": False,
            "faces": False,
            "colorize": False,
            "scratches": False,
        },
    )
    assert neither.status_code == 422

    def finish(body: dict) -> dict:
        queued = client.post(url, json=body)
        assert queued.status_code == 202
        assert app.state.worker.process_available() == 1
        done = client.get(f"/api/scans/{scan_id}").json()["regions"]
        return next(item for item in done if item["id"] == region_id)

    denoised = finish(
        {
            "upscale": False,
            "denoise": True,
            "faces": False,
            "colorize": False,
            "scratches": False,
        }
    )
    assert denoised["retouch_denoise"] is True
    assert denoised["retouch_upscale"] is False
    assert denoised["retouch_signature"].endswith("u0d1f0c0s0")
    _assert_derivative(services, scan_id, denoised, scale=1, color=(0, 0, 255))

    scaled = finish(
        {
            "upscale": True,
            "denoise": False,
            "faces": False,
            "colorize": False,
            "scratches": False,
        }
    )
    assert scaled["retouch_denoise"] is False
    assert scaled["retouch_signature"].endswith("u1d0f0c0s0")
    _assert_derivative(services, scan_id, scaled, scale=2, color=(255, 0, 0))

    both = finish(
        {
            "upscale": True,
            "denoise": True,
            "faces": False,
            "colorize": False,
            "scratches": False,
        }
    )
    assert both["retouch_signature"].endswith("u1d1f0c0s0")
    _assert_derivative(services, scan_id, both, scale=2, color=(255, 0, 0))

    stale = client.patch(
        f"/api/scans/{scan_id}/regions/{region_id}",
        json={"retouch_denoise": False},
    )
    assert stale.status_code == 200
    assert stale.json()["retouch_upscale"] is True
    assert stale.json()["retouch_denoise"] is False
    assert stale.json()["retouch_status"] == "stale"
    assert stale.json()["retouch_ready"] is False


def test_an_old_combined_signature_stays_current() -> None:
    now = utcnow()
    region = Region(
        id="region",
        scan_id="scan",
        position=0,
        center_x=10,
        center_y=20,
        width=30,
        height=40,
        angle_deg=1.5,
        quarter_turns=0,
        created_at=now,
        updated_at=now,
        retouch_upscale=True,
        retouch_denoise=True,
        retouch_status="ready",
        retouch_path="scans/scan/retouch/region.png",
    )
    geometry = crop_signature(10, 20, 30, 40, 1.5, 0)
    region.retouch_signature = f"{geometry}|u1f0c0s0"
    assert options_from_token("u1f0c0s0") == RetouchOptions(upscale=True, denoise=True)
    assert retouch_is_current(region)
    assert flags_restore_faces(region.retouch_signature) is False
    assert flags_restore_faces(f"{geometry}|u1d0f1c0s0") is True
    region.retouch_denoise = False
    assert retouch_is_current(region) is False
    region.retouch_denoise = True
    region.retouch_signature = f"{geometry}|u1d1f0c0s0"
    assert retouch_is_current(region)


def test_saved_settings_without_denoise_still_mean_both(client, app_bundle) -> None:
    saved = client.put(
        "/api/settings",
        json={
            "immich_base_url": "",
            "immich_api_key": "",
            "output_format": "jpeg",
            "jpeg_quality": 95,
            "default_album_id": "",
            "retouch_upscale": True,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["retouch_denoise"] is True

    explicit = client.put(
        "/api/settings",
        json={
            "immich_base_url": "",
            "immich_api_key": "",
            "output_format": "jpeg",
            "jpeg_quality": 95,
            "default_album_id": "",
            "retouch_upscale": True,
            "retouch_denoise": False,
        },
    )
    assert explicit.json()["retouch_upscale"] is True
    assert explicit.json()["retouch_denoise"] is False

    _app, services = app_bundle
    with services.session_factory() as session:
        stored = session.get(Setting, "retouch_denoise")
        assert stored is not None
        session.delete(stored)
        session.commit()
    again = client.get("/api/settings").json()
    assert again["retouch_upscale"] is True
    assert again["retouch_denoise"] is True

    explicit = client.put(
        "/api/settings",
        json={
            "immich_base_url": "",
            "immich_api_key": "",
            "output_format": "jpeg",
            "jpeg_quality": 95,
            "default_album_id": "",
            "retouch_upscale": True,
            "retouch_denoise": False,
        },
    )
    scan_id = _import_bed(services, encode_png(make_bed(speck=False)))
    assert _app.state.worker.process_available() == 1
    photo = client.get(f"/api/scans/{scan_id}").json()["regions"][0]
    assert photo["retouch_upscale"] is True
    assert photo["retouch_denoise"] is False


def test_existing_rows_copy_upscale_into_denoise(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    configuration.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "alembic"),
    )
    configuration.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(configuration, "0002_retouch")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO scans (id, created_at, original_filename, width, height, upload_state) "
            "VALUES ('scan', '2020-01-01 00:00:00', 'bed.png', 10, 10, 'pending')"
        )
        connection.executemany(
            "INSERT INTO regions ("
            "id, scan_id, position, center_x, center_y, width, height, angle_deg, "
            "upload_status, created_at, updated_at, retouch_upscale"
            ") VALUES (?, 'scan', ?, 1, 1, 4, 4, 0, 'pending', "
            "'2020-01-01 00:00:00', '2020-01-01 00:00:00', ?)",
            (("on", 0, 1), ("off", 1, 0)),
        )
    command.upgrade(configuration, "head")
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute("SELECT id, retouch_denoise FROM regions"))
    assert rows == {"on": 1, "off": 0}


def test_retouch_stage_stays_with_later_percents() -> None:
    region_id = "stage-region"
    clear_retouch_progress(region_id)
    try:
        set_retouch_progress(region_id, 10)
        set_retouch_stage(region_id, "Denoising")
        set_retouch_progress(region_id, 40)
        assert retouch_progress(region_id) == 40
        assert retouch_stage(region_id) == "Denoising"
    finally:
        clear_retouch_progress(region_id)
    assert retouch_stage(region_id) is None


def test_scale_only_asks_for_the_detail_model_and_both_do_not(tmp_path) -> None:
    models = tmp_path
    (models / CATALOG["upscale"].filename).write_bytes(b"onnx")
    OnnxRetoucher(models)._require(RetouchOptions(upscale=True, denoise=True))
    with pytest.raises(MissingWeights, match="realesr-general-wdn-x4v3.onnx"):
        OnnxRetoucher(models)._require(RetouchOptions(upscale=True))
    (models / CATALOG["scale"].filename).write_bytes(b"onnx")
    OnnxRetoucher(models)._require(RetouchOptions(upscale=True))
    with pytest.raises(MissingWeights, match="realesr-general-x4v3.onnx"):
        OnnxRetoucher(tmp_path / "empty")._require(RetouchOptions(denoise=True))


def _assert_derivative(services, scan_id: str, region: dict, *, scale: int, color: tuple) -> None:
    bed, _dpi = load_rgb(services.storage.root / "scans" / scan_id / "original.png")
    expected = upright_crop(
        bed,
        region["center_x"],
        region["center_y"],
        region["width"],
        region["height"],
        region["angle_deg"],
        region["quarter_turns"],
    )
    derivative, _dpi = load_rgb(services.storage.absolute(_retouch_path(services, region["id"])))
    assert derivative.shape[0] == expected.shape[0] * scale
    assert derivative.shape[1] == expected.shape[1] * scale
    assert np.all(derivative[:12, :12] == color)


def _assert_crop_was_kept(services, scan_id: str, region: dict, *, scaled: bool) -> None:
    bed, _dpi = load_rgb(services.storage.root / "scans" / scan_id / "original.png")
    expected = upright_crop(
        bed,
        region["center_x"],
        region["center_y"],
        region["width"],
        region["height"],
        region["angle_deg"],
        region["quarter_turns"],
    )
    crop_path = services.storage.root / "scans" / scan_id / "crops" / f"{region['id']}.png"
    saved, _dpi = load_rgb(crop_path)
    assert np.array_equal(saved, expected)
    derivative, _dpi = load_rgb(services.storage.absolute(_retouch_path(services, region["id"])))
    if scaled:
        assert derivative.shape[0] == expected.shape[0] * 2
        assert np.all(derivative[:12, :12] == (255, 0, 0))
    else:
        assert derivative.shape[:2] == expected.shape[:2]
        assert np.all(derivative[:12, -12:] == (0, 255, 0))
    assert not np.all(saved[:12, :12] == (255, 0, 0))


def _retouch_path(services, region_id: str) -> str:
    with services.session_factory() as session:
        stored = session.get(Region, region_id)
        assert stored is not None
        assert stored.retouch_path
        return stored.retouch_path


def _png(content: bytes) -> Image.Image:
    from io import BytesIO

    return Image.open(BytesIO(content))
