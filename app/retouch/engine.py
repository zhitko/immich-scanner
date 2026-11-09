from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.retouch.catalog import CATALOG, ModelSpec, restoration_for, specs_for
from app.retouch.cleanup import deblur, gentle_denoise, remove_dust
from app.retouch.detection import learned_scratch_mask
from app.retouch.imageops import (
    apply_ab,
    as_nchw,
    byte_to_rgb,
    chroma_collapsed,
    colorizer_tone,
    from_model,
    lab_gray_rgb,
    masked_tile_count,
    masked_tiles,
    paste_face,
    square_tile_count,
    tame_ab,
    tiled_map,
    unit_to_rgb,
    warp_face,
)
from app.retouch.levels import correct_color_cast, restore_contrast
from app.retouch.options import RetouchOptions
from app.retouch.session import open_session

_LAMA_SIZE = 512
_LAMA_OVERLAP = 64
# A neural tile is one unit. The scratch mask and colorizer are weighed so the
# percent still moves while those stages run, and so upscale (the long part) dominates.
_MASK_UNITS = 2
_COLOR_UNITS = 4
_FACE_DETECT_UNITS = 1
_FACE_UNITS = 3
_FACE_GUESS = 1
_RESIZE_UNITS = 1


class MissingWeights(RuntimeError):
    pass


class Retoucher(Protocol):
    def apply(
        self,
        image: np.ndarray,
        options: RetouchOptions,
        on_progress: Callable[[int], None] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> np.ndarray: ...


class OnnxRetoucher:
    """One photo at a time. Sessions stay loaded until their file on disk changes."""

    def __init__(
        self,
        models_dir: Path,
        execution: str = "cpu",
        openvino_device: str = "CPU",
    ) -> None:
        self.models_dir = models_dir
        self.execution = execution
        self.openvino_device = openvino_device
        self._sessions: dict[str, tuple[tuple[int, int], object]] = {}

    def apply(
        self,
        image: np.ndarray,
        options: RetouchOptions,
        on_progress: Callable[[int], None] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> np.ndarray:
        self._require(options)
        budget = self._budget(image, options, on_progress)
        # Scratches, levels and color run on the crop. Scale and denoise are one
        # Real-ESRGAN pass after that: both networks emit 4×, so a second pass
        # would enlarge twice. Faces run last and see the image that will be saved.
        result = image
        if options.dust:
            _announce(on_stage, "Removing dust and small spots")
            result = remove_dust(result)
            if budget is not None:
                budget.add(1)
        if options.scratches:
            _announce(on_stage, "Detecting scratches")
            mask = learned_scratch_mask(self._session(CATALOG["scratch-detection"]), result)
            if budget is not None:
                budget.add(_MASK_UNITS)
            if mask.any():
                _announce(on_stage, "Filling scratches")
                tile_h, tile_w = self._lama_tile()
                if budget is not None:
                    extra = masked_tile_count(_inpaint_mask(mask), tile_h, tile_w, _LAMA_OVERLAP)
                    if extra:
                        budget.resize(budget.total + extra)
                result = self._inpaint(
                    result,
                    mask,
                    on_tile=None if budget is None else lambda: budget.add(1),
                )
        if options.gentle_denoise:
            _announce(on_stage, "Gently denoising")
            result = gentle_denoise(result)
            if budget is not None:
                budget.add(1)
        if options.deblur:
            _announce(on_stage, "Reducing mild blur")
            result = deblur(result)
            if budget is not None:
                budget.add(1)
        if options.color_balance:
            _announce(on_stage, "Correcting color cast")
            result = correct_color_cast(result)
            if budget is not None:
                budget.add(1)
        if options.contrast:
            _announce(on_stage, "Restoring contrast")
            result = restore_contrast(result)
            if budget is not None:
                budget.add(1)
        if options.colorize:
            _announce(on_stage, "Colorizing")
            result = self._colorize(result)
            if budget is not None:
                budget.add(_COLOR_UNITS)
        plan = restoration_for(upscale=options.upscale, denoise=options.denoise)
        if plan is not None:
            _announce(on_stage, plan.stage)
            result = self._restore(
                result,
                plan.model_id,
                keep_scale=plan.keep_scale,
                denoise_strength=1.0 if options.denoise else 0.0,
                on_tile=None if budget is None else lambda: budget.add(1),
            )
        if options.upscale and options.output_scale == 2:
            _announce(on_stage, "Resizing to 2×")
            result = cv2.resize(
                result, (image.shape[1] * 2, image.shape[0] * 2), interpolation=cv2.INTER_AREA
            )
            if budget is not None:
                budget.add(1)
        if options.faces:
            _announce(on_stage, "Restoring faces")
            result = self._faces(
                result,
                on_detected=None if budget is None else budget.note_faces,
                on_face=None if budget is None else lambda: budget.add(_FACE_UNITS),
            )
        if budget is not None:
            budget.finish()
        return np.ascontiguousarray(result)

    def _budget(
        self,
        image: np.ndarray,
        options: RetouchOptions,
        on_progress: Callable[[int], None] | None,
    ) -> "_Budget | None":
        if on_progress is None:
            return None
        total = 0
        total += int(options.dust) + int(options.deblur) + int(options.gentle_denoise)
        total += int(options.upscale and options.output_scale == 2)
        face_estimate = 0
        if options.scratches:
            total += _MASK_UNITS
        total += int(options.color_balance) + int(options.contrast)
        if options.colorize:
            total += _COLOR_UNITS
        plan = restoration_for(upscale=options.upscale, denoise=options.denoise)
        if plan is not None:
            tile, overlap = self._layout(self._session(CATALOG[plan.model_id]))
            total += square_tile_count(image.shape[0], image.shape[1], tile, overlap)
            if not plan.keep_scale:
                total += _RESIZE_UNITS
        if options.faces:
            # A guess, so the bar does not cost a detection. The real one corrects it.
            face_estimate = _FACE_GUESS
            total += _FACE_DETECT_UNITS + face_estimate * _FACE_UNITS
        return _Budget(total, face_estimate, on_progress)

    def _require(self, options: RetouchOptions) -> None:
        missing = [
            (name, spec.license_id)
            for spec in specs_for(
                upscale=options.upscale,
                denoise=options.denoise,
                faces=options.faces,
                colorize=options.colorize,
                scratches=options.scratches,
            )
            for name in spec.filenames()
            if not (self.models_dir / name).is_file()
        ]
        if not missing:
            return
        names = ", ".join(f"{name} ({license_id})" for name, license_id in missing)
        raise MissingWeights(
            "Missing weights: "
            f"{names}. They are not downloaded automatically. "
            "Read each license, then download it under Settings or place the file "
            "in the models directory."
        )

    def _session(self, spec: ModelSpec):
        path = self.models_dir / spec.filename
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._sessions.get(spec.id)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        # GPU acceleration is supported for the two Real-ESRGAN exports. LaMa's
        # dynamic shapes cannot compile on the Intel GPU; other restoration
        # networks retain their established CPU execution path as well.
        execution = self.execution if spec.id in {"upscale", "scale"} else "cpu"
        opened = open_session(path, execution, self.openvino_device)
        self._sessions[spec.id] = (stamp, opened)
        return opened

    def _layout(self, session) -> tuple[int, int]:
        spatial = _spatial(session.get_inputs()[0].shape)
        tile = spatial[0] or spatial[1] or 256
        overlap = min(16, max(0, tile // 8))
        return tile, overlap

    def _restore(
        self,
        image: np.ndarray,
        model_id: str,
        *,
        keep_scale: bool,
        denoise_strength: float,
        on_tile: Callable[[], None] | None = None,
    ) -> np.ndarray:
        session = self._session(CATALOG[model_id])
        tile, overlap = self._layout(session)
        result = tiled_map(
            image,
            lambda tile_image: _run_upscale_tile(session, tile_image, denoise_strength),
            tile=tile,
            overlap=overlap,
            on_tile=on_tile,
        )
        if keep_scale:
            return result
        height, width = image.shape[:2]
        if result.shape[0] != height or result.shape[1] != width:
            result = cv2.resize(result, (width, height), interpolation=cv2.INTER_LANCZOS4)
        if on_tile is not None:
            on_tile()
        return result

    def _colorize(self, image: np.ndarray) -> np.ndarray:
        session = self._session(CATALOG["colorize"])
        height, width = _spatial(session.get_inputs()[0].shape)
        feed_h = height or 512
        feed_w = width or 512
        # This export returns ~0, plus a patch of huge a,b, on a high-key or flat scan.
        # The patch resizes into colored dots and the rest stays gray. A second pass
        # feeds a print-like tone curve. Lightness below still comes from the scan.
        ab = self._color_ab(session, image, feed_w, feed_h)
        if chroma_collapsed(ab):
            ab = self._color_ab(session, colorizer_tone(image), feed_w, feed_h)
        return apply_ab(image, tame_ab(ab))

    def _color_ab(self, session, image: np.ndarray, feed_w: int, feed_h: int) -> np.ndarray:
        tensor = np.transpose(lab_gray_rgb(image, feed_w, feed_h), (2, 0, 1))[None]
        output = from_model(session.run(None, {session.get_inputs()[0].name: tensor})[0])
        if output.shape[2] != 2:
            raise RuntimeError("the colorizer did not return Lab a and b")
        return output

    def _lama_tile(self) -> tuple[int, int]:
        session = self._session(CATALOG["inpaint"])
        fixed_h, fixed_w = _spatial(session.get_inputs()[0].shape)
        return fixed_h or _LAMA_SIZE, fixed_w or _LAMA_SIZE

    def _inpaint(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        on_tile: Callable[[], None] | None = None,
    ) -> np.ndarray:
        session = self._session(CATALOG["inpaint"])
        tile_h, tile_w = self._lama_tile()
        # Give the model clean context beyond the detected damage. Feather only
        # this extra margin; blurring the original mask mixes scratches back in.
        holes = _inpaint_mask(mask)
        filled = masked_tiles(
            image,
            holes,
            lambda tile, tile_mask: _run_lama(session, tile, tile_mask),
            tile_h=tile_h,
            tile_w=tile_w,
            overlap=_LAMA_OVERLAP,
            on_tile=on_tile,
        )
        soft = cv2.GaussianBlur(holes.astype(np.float32), (5, 5), 0)
        soft[mask] = 1.0
        soft = soft[..., None]
        blended = filled.astype(np.float32) * soft + image.astype(np.float32) * (1.0 - soft)
        return np.clip(blended, 0, 255).astype(np.uint8)

    def _faces(
        self,
        image: np.ndarray,
        on_detected: Callable[[int], None] | None = None,
        on_face: Callable[[], None] | None = None,
    ) -> np.ndarray:
        landmarks = detect_faces(image, self.models_dir / CATALOG["face-detection"].filename)
        if on_detected is not None:
            on_detected(len(landmarks))
        if not landmarks:
            return image
        session = self._session(CATALOG["faces"])
        result = image
        for points in landmarks:
            warped = warp_face(result, points)
            if warped is not None:
                aligned, matrix = warped
                restored = _run_gfpgan(session, aligned)
                result = paste_face(result, matrix, restored)
            if on_face is not None:
                on_face()
        return result


class _Budget:
    """Work units for one retouch. The shown percent never moves backwards and stops at 99."""

    def __init__(self, total: int, face_estimate: int, report: Callable[[int], None]) -> None:
        self.total = max(1, total)
        self.done = 0
        self.shown = -1
        self._faces = face_estimate
        self._report = report

    def add(self, units: int) -> None:
        if units <= 0:
            return
        self.done += units
        self._emit()

    def resize(self, total: int) -> None:
        self.total = max(self.done, total, 1)
        self._emit()

    def note_faces(self, count: int) -> None:
        delta = (count - self._faces) * _FACE_UNITS
        if delta:
            self.resize(self.total + delta)
        self._faces = count
        self.add(_FACE_DETECT_UNITS)

    def finish(self) -> None:
        self.done = max(self.done, self.total)
        self._emit()

    def _emit(self) -> None:
        percent = min(99, (self.done * 100) // self.total)
        if percent <= self.shown:
            return
        self.shown = percent
        self._report(percent)


def detect_faces(image: np.ndarray, model_path: Path) -> list[np.ndarray]:
    height, width = image.shape[:2]
    scale = 1.0
    working = image
    long_edge = max(height, width)
    if long_edge > 1280:
        scale = 1280 / long_edge
        size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        working = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    detector = cv2.FaceDetectorYN.create(
        str(model_path),
        "",
        (working.shape[1], working.shape[0]),
        0.6,
        0.3,
        20,
    )
    _faces_count, faces = detector.detect(cv2.cvtColor(working, cv2.COLOR_RGB2BGR))
    if faces is None:
        return []
    found: list[np.ndarray] = []
    for row in faces:
        points = row[4:14].reshape(5, 2).astype(np.float32)
        if scale != 1.0:
            points /= scale
        found.append(points)
    return found


def _run_upscale_tile(
    session,
    tile: np.ndarray,
    denoise_strength: float | None = None,
) -> np.ndarray:
    tensor = as_nchw(tile)
    feeds = {session.get_inputs()[0].name: tensor}
    if len(session.get_inputs()) > 1:
        # Strength 0 is the detail-preserving network. Strength 1 is the
        # denoising network. The pinned exports have no such input.
        if denoise_strength is None:
            raise RuntimeError("this upscaler input is a denoise strength")
        feeds[session.get_inputs()[1].name] = np.array(denoise_strength, dtype=np.float32)
    # Real-ESRGAN returns 0..1 and overshoots a little at hard edges.
    return unit_to_rgb(from_model(session.run(None, feeds)[0]))


def _announce(on_stage: Callable[[str], None] | None, stage: str) -> None:
    if on_stage is not None:
        on_stage(stage)


def _run_gfpgan(session, face: np.ndarray) -> np.ndarray:
    tensor = face.astype(np.float32) / 255.0
    tensor = (tensor - 0.5) / 0.5
    nchw = np.transpose(tensor, (2, 0, 1))[None]
    output = from_model(session.run(None, {session.get_inputs()[0].name: nchw})[0])
    # GFPGAN's own preprocessing maps 0..1 to -1..1, and the graph returns that range.
    image = unit_to_rgb(output * 0.5 + 0.5)
    if image.shape[0] != 512 or image.shape[1] != 512:
        image = cv2.resize(image, (512, 512), interpolation=cv2.INTER_LINEAR)
    return image


def _inpaint_mask(mask: np.ndarray) -> np.ndarray:
    margin = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    return cv2.dilate(mask.astype(np.uint8), margin).astype(bool)


def _run_lama(session, tile: np.ndarray, tile_mask: np.ndarray) -> np.ndarray:
    image_nchw = as_nchw(tile)
    mask_nchw = tile_mask.astype(np.float32)[None, None]
    output = from_model(session.run(None, _lama_feeds(session, image_nchw, mask_nchw))[0])
    # Carve's export takes 0..1 and returns 0..255.
    return byte_to_rgb(output)


def _lama_feeds(session, image_nchw: np.ndarray, mask_nchw: np.ndarray) -> dict[str, np.ndarray]:
    feeds: dict[str, np.ndarray] = {}
    for item in session.get_inputs():
        channels = item.shape[1] if len(item.shape) > 1 else None
        if channels == 1 or "mask" in item.name.lower():
            feeds[item.name] = mask_nchw
        else:
            feeds[item.name] = image_nchw
    return feeds


def _spatial(shape: list[object]) -> tuple[int | None, int | None]:
    return _dim(shape[2]) if len(shape) > 2 else None, _dim(shape[3]) if len(shape) > 3 else None


def _dim(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None
