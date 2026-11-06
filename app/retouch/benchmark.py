"""Compare scratch masks on local crops without changing saved retouches.

python -m app.retouch.benchmark --output /tmp/opencode/scratches photo.png
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.retouch.catalog import CATALOG
from app.retouch.detection import learned_scratch_mask
from app.retouch.engine import OnnxRetoucher
from app.retouch.scratch import scratch_mask


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--models", type=Path, default=Path("data/models"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair", action="store_true", help="also run LaMa on the learned mask")
    parser.add_argument(
        "--region",
        nargs=4,
        type=float,
        metavar=("X0", "Y0", "X1", "Y1"),
        help="normalized rectangle to measure, e.g. .46 .54 .66 .99 for the tie",
    )
    args = parser.parse_args()
    if args.region:
        x0, y0, x1, y1 = args.region
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            parser.error("region must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    args.output.mkdir(parents=True, exist_ok=True)
    retoucher = OnnxRetoucher(args.models)
    session = retoucher._session(CATALOG["scratch-detection"])
    report = []
    for index, path in enumerate(args.images):
        image = np.asarray(Image.open(path).convert("RGB"))
        start = time.perf_counter()
        learned = learned_scratch_mask(session, image)
        elapsed = time.perf_counter() - start
        old = scratch_mask(image)
        item = {
            "image": str(path),
            "detector_seconds": elapsed,
            "old_fraction": float(old.mean()),
            "learned_fraction": float(learned.mean()),
        }
        if args.region:
            h, w = learned.shape
            x0, y0, x1, y1 = args.region
            roi = np.s_[
                int(y0 * h) : max(int(y0 * h) + 1, int(y1 * h)),
                int(x0 * w) : max(int(x0 * w) + 1, int(x1 * w)),
            ]
            item["old_region_fraction"] = float(old[roi].mean())
            item["learned_region_fraction"] = float(learned[roi].mean())
        stem = f"{index:02d}-{path.stem}"
        panels = []
        for name, mask in (("old", old), ("learned", learned)):
            Image.fromarray(mask.astype(np.uint8) * 255).save(
                args.output / f"{stem}-{name}-mask.png"
            )
            overlay = image.copy()
            overlay[mask] = image[mask] * 0.35 + np.array([165, 0, 0])
            panels.append(overlay)
        if args.repair:
            repaired = retoucher._inpaint(image, learned)
            Image.fromarray(repaired).save(args.output / f"{stem}-repaired.png")
            panels.append(repaired)
        h, w = image.shape[:2]
        preview = np.concatenate(
            [cv2.resize(panel, (max(1, round(w * 800 / h)), 800)) for panel in [image, *panels]],
            axis=1,
        )
        Image.fromarray(preview).save(args.output / f"{stem}-comparison.jpg")
        report.append(item)
        print(json.dumps(item), flush=True)
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
