"""Conservative masks from Microsoft's old-photo scratch detector."""

import cv2
import numpy as np
from PIL import Image

from app.imaging.io import as_byte_rgb

_SHORT_SIDE = 256
_CONFIDENCE = 0.7
_EDGE_CONFIDENCE = 0.2


def scratch_probabilities(
    session, image: np.ndarray, *, short_side: int = _SHORT_SIDE
) -> np.ndarray:
    """Run the sigmoid-included ONNX export at its reference training scale.

    Whole-photo context helps distinguish repeated fabric and hair from damage.
    Feeding full-resolution tiles instead changes the apparent scale of texture.
    """

    height, width = image.shape[:2]
    scale = short_side / min(height, width)
    size = (max(16, round(width * scale / 16) * 16), max(16, round(height * scale / 16) * 16))
    # Match the upstream PIL resize -> grayscale -> [-1, 1] preprocessing.
    gray = Image.fromarray(as_byte_rgb(image)).resize(size, Image.Resampling.BICUBIC).convert("L")
    tensor = (np.asarray(gray, dtype=np.float32) / 127.5 - 1.0)[None, None]
    output = np.asarray(session.run(None, {session.get_inputs()[0].name: tensor})[0])
    if output.shape != (1, 1, size[1], size[0]):
        raise RuntimeError("the scratch detector did not return a probability map")
    if not np.isfinite(output).all() or output.min() < 0 or output.max() > 1:
        raise RuntimeError("the scratch detector returned invalid probabilities")
    return cv2.resize(output[0, 0], (width, height), interpolation=cv2.INTER_LINEAR)


def learned_scratch_mask(session, image: np.ndarray) -> np.ndarray:
    probabilities = scratch_probabilities(session, image)
    if not (probabilities >= _CONFIDENCE).any():
        return np.zeros(probabilities.shape, dtype=bool)
    detail = scratch_probabilities(session, image, short_side=512)
    return repair_mask(probabilities, confirmation=detail)


def repair_mask(probabilities: np.ndarray, *, confirmation: np.ndarray | None = None) -> np.ndarray:
    """Include uncertain edges of confirmed damage, without seeding new holes.

    A 256-pixel detector cannot locate every parallel crack in a high-resolution
    crease. Thresholding only its confident centre leaves damaged context for
    LaMa to copy. Grow through lower-confidence pixels connected to that centre,
    bounded to two detector pixels, then cover half a pixel of localization error.
    The bound prevents a weak texture region from flooding the whole picture.
    When a fine pass is available, its edge support also limits the repair
    locally; accepting a long crease must not approve a wide branch over a face.
    """

    core = probabilities >= _CONFIDENCE
    if confirmation is not None:
        # At 256 pixels a necklace can look like one bright scratch. Require
        # majority support at 512, where individual beads become distinguishable.
        # Component agreement rejects false positives, but cannot locate their
        # edges. Constrain even accepted cores to local fine-scale support;
        # the final margin below tolerates small localization errors and gaps.
        count, labels = cv2.connectedComponents(core.astype(np.uint8), connectivity=8)
        sizes = np.bincount(labels.ravel(), minlength=count)
        hits = np.bincount(labels[confirmation >= _CONFIDENCE], minlength=count)
        accepted = (hits >= sizes * 0.5) & (sizes > 0)
        accepted[0] = False
        core = accepted[labels] & (confirmation >= _EDGE_CONFIDENCE)
    if not core.any():
        return core
    pixel = max(1.0, min(core.shape) / _SHORT_SIDE)
    distance = cv2.distanceTransform((~core).astype(np.uint8), cv2.DIST_L2, 5)
    candidates = (probabilities >= _EDGE_CONFIDENCE) & (distance <= 2 * pixel)
    if confirmation is not None:
        candidates &= confirmation >= _EDGE_CONFIDENCE
    count, labels = cv2.connectedComponents(candidates.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[np.unique(labels[core])] = True
    keep[0] = False
    margin = max(1, int(np.ceil(pixel / 2)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1, 2 * margin + 1))
    return cv2.dilate(keep[labels].astype(np.uint8), kernel).astype(bool)
