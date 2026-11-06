"""Conservative masks from Microsoft's old-photo scratch detector."""

import cv2
import numpy as np
from PIL import Image

_SHORT_SIDE = 256
_CONFIDENCE = 0.7


def scratch_probabilities(session, image: np.ndarray) -> np.ndarray:
    """Run the sigmoid-included ONNX export at its reference training scale.

    Whole-photo context helps distinguish repeated fabric and hair from damage.
    Feeding full-resolution tiles instead changes the apparent scale of texture.
    """

    height, width = image.shape[:2]
    scale = _SHORT_SIDE / min(height, width)
    size = (max(16, round(width * scale / 16) * 16), max(16, round(height * scale / 16) * 16))
    # Match the upstream PIL resize -> grayscale -> [-1, 1] preprocessing.
    gray = Image.fromarray(image).resize(size, Image.Resampling.BICUBIC).convert("L")
    tensor = (np.asarray(gray, dtype=np.float32) / 127.5 - 1.0)[None, None]
    output = np.asarray(session.run(None, {session.get_inputs()[0].name: tensor})[0])
    if output.shape != (1, 1, size[1], size[0]):
        raise RuntimeError("the scratch detector did not return a probability map")
    if not np.isfinite(output).all() or output.min() < 0 or output.max() > 1:
        raise RuntimeError("the scratch detector returned invalid probabilities")
    return cv2.resize(output[0, 0], (width, height), interpolation=cv2.INTER_LINEAR)


def learned_scratch_mask(session, image: np.ndarray) -> np.ndarray:
    # Threshold after interpolation. Enlarging a binary low-resolution mask
    # makes blocky holes; geometric bridging can reconnect intact stripes.
    return scratch_probabilities(session, image) >= _CONFIDENCE
