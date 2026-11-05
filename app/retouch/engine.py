from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.retouch.catalog import CATALOG, ModelSpec, specs_for
from app.retouch.imageops import (
    apply_ab,
    as_nchw,
    byte_to_rgb,
    from_model,
    lab_gray_rgb,
    masked_tiles,
    paste_face,
    tiled_map,
    unit_to_rgb,
    warp_face,
)
from app.retouch.options import RetouchOptions
from app.retouch.scratch import scratch_mask
from app.retouch.session import open_session

_DENOISE = np.array(0.5, dtype=np.float32)
_LAMA_SIZE = 512
_LAMA_OVERLAP = 64


class MissingWeights(RuntimeError):
    pass


class Retoucher(Protocol):
    def apply(self, image: np.ndarray, options: RetouchOptions) -> np.ndarray: ...


class OnnxRetoucher:
    """One photo at a time. Sessions stay loaded until their file on disk changes."""

    def __init__(
        self,
        models_dir: Path,
        execution: str = "cpu",
        openvino_device: str = "CPU_FP32",
    ) -> None:
        self.models_dir = models_dir
        self.execution = execution
        self.openvino_device = openvino_device
        self._sessions: dict[str, tuple[tuple[int, int], object]] = {}

    def apply(self, image: np.ndarray, options: RetouchOptions) -> np.ndarray:
        self._require(options)
        # Scratches and color run on the crop. The upscaler runs next, then faces,
        # so restoration sees the enlarged print and the other models do not.
        result = image
        if options.scratches:
            mask = scratch_mask(result)
            if mask.any():
                result = self._inpaint(result, mask)
        if options.colorize:
            result = self._colorize(result)
        if options.upscale:
            result = self._upscale(result)
        if options.faces:
            result = self._faces(result)
        return np.ascontiguousarray(result)

    def _require(self, options: RetouchOptions) -> None:
        missing = [
            (name, spec.license_id)
            for spec in specs_for(
                upscale=options.upscale,
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
        opened = open_session(path, self.execution, self.openvino_device)
        self._sessions[spec.id] = (stamp, opened)
        return opened

    def _upscale(self, image: np.ndarray) -> np.ndarray:
        session = self._session(CATALOG["upscale"])
        spatial = _spatial(session.get_inputs()[0].shape)
        tile = spatial[0] or spatial[1] or 256
        overlap = min(16, max(0, tile // 8))
        return tiled_map(
            image,
            lambda tile_image: _run_upscale_tile(session, tile_image),
            tile=tile,
            overlap=overlap,
        )

    def _colorize(self, image: np.ndarray) -> np.ndarray:
        session = self._session(CATALOG["colorize"])
        height, width = _spatial(session.get_inputs()[0].shape)
        feed_h = height or 512
        feed_w = width or 512
        tensor = np.transpose(lab_gray_rgb(image, feed_w, feed_h), (2, 0, 1))[None]
        output = from_model(session.run(None, {session.get_inputs()[0].name: tensor})[0])
        if output.shape[2] != 2:
            raise RuntimeError("the colorizer did not return Lab a and b")
        return apply_ab(image, output)

    def _inpaint(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        session = self._session(CATALOG["inpaint"])
        fixed_h, fixed_w = _spatial(session.get_inputs()[0].shape)
        filled = masked_tiles(
            image,
            mask,
            lambda tile, tile_mask: _run_lama(session, tile, tile_mask),
            tile_h=fixed_h or _LAMA_SIZE,
            tile_w=fixed_w or _LAMA_SIZE,
            overlap=_LAMA_OVERLAP,
        )
        soft = cv2.GaussianBlur(mask.astype(np.float32), (5, 5), 0)[..., None]
        blended = filled.astype(np.float32) * soft + image.astype(np.float32) * (1.0 - soft)
        return np.clip(blended, 0, 255).astype(np.uint8)

    def _faces(self, image: np.ndarray) -> np.ndarray:
        landmarks = detect_faces(image, self.models_dir / CATALOG["face-detection"].filename)
        if not landmarks:
            return image
        session = self._session(CATALOG["faces"])
        result = image
        for points in landmarks:
            warped = warp_face(result, points)
            if warped is None:
                continue
            aligned, matrix = warped
            restored = _run_gfpgan(session, aligned)
            result = paste_face(result, matrix, restored)
        return result


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


def _run_upscale_tile(session, tile: np.ndarray) -> np.ndarray:
    tensor = as_nchw(tile)
    feeds = {session.get_inputs()[0].name: tensor}
    if len(session.get_inputs()) > 1:
        feeds[session.get_inputs()[1].name] = _DENOISE
    # Real-ESRGAN returns 0..1 and overshoots a little at hard edges.
    return unit_to_rgb(from_model(session.run(None, feeds)[0]))


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
