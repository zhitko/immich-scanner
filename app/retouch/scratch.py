import cv2
import numpy as np

# A long hat kernel treats every detail thinner than itself as a stroke and joins a
# crease to the rest of the print. The crease is then discarded with the filled areas.
_THICKNESS = 0.0026
_WIDE = 0.0055
_MIN_LENGTH = 0.012
_STRONG = 40
_HAIRLINE = 24
_BRIDGE = 16
# Gray levels a band pixel must differ from the picture continued across the band.
_DEVIATION = 16
# Top-hat and black-hat level for a crack inside the fold corridor.
_CRACK = 13
_SPECK = 40


def scratch_mask(image: np.ndarray) -> np.ndarray:
    """Light or dark strokes, including a crease that fades along its length.

    Filled areas are left alone. A fold is covered as one band, including the
    stretch where it crosses pale paper and the stroke itself is hard to see.
    A tear's shoulder is included, so the fill cannot copy the rest of the tear
    back in. A hairline on flat paper stays narrow.
    """

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    short = min(height, width)
    thickness = _odd(max(9, short * _THICKNESS))
    wide = _odd(max(thickness + 6, short * _WIDE))
    min_length = max(24, int(round(short * _MIN_LENGTH)))
    fine = _line_response(gray, thickness)
    seeds = _strokes(fine, _STRONG, thickness * 0.8, min_length)
    seeds |= _strokes(fine, _HAIRLINE, 2.2, min_length)
    bridged = _bridge(seeds, _line_response(gray, wide), search=max(14, thickness + 6))
    radius = max(12, int(round(short * 0.013)))
    min_span = max(80, int(round(short * 0.02)))
    widened = _widen_creases(bridged, radius=radius, min_span=min_span)
    # After the fold band. Attaching first would join stray marks into a fold.
    attached = _attach_fragments(widened, fine)
    strokes = seeds | bridged | (attached & ~widened)
    covered = _cover_ridge(gray, attached)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    band = cv2.dilate(covered.astype(np.uint8), kernel).astype(bool)
    reach = max(6, int(round(short * 0.006)))
    return _tighten(gray, band, strokes, reach=reach, min_span=min_span)


def _tighten(
    gray: np.ndarray,
    band: np.ndarray,
    strokes: np.ndarray,
    *,
    reach: int,
    min_span: int,
) -> np.ndarray:
    """Keep the cracks inside the band, not the whole band.

    A fold band is much wider than its cracks. Filling all of it erases whatever
    runs under the fold: medals, a dress print, fingers. Thin light or dark lines
    close to the stroke are kept. So is a wide lift that runs along the stroke,
    like a tear's shoulder. A shape that only crosses the fold stays in the photo.
    """

    if not band.any():
        return band
    corridor = cv2.dilate(strokes.astype(np.uint8), _kernel(2 * reach + 1)).astype(bool) & band
    small = _kernel(9)
    light = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, small)
    dark = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, small)
    cracks = corridor & ((light >= _CRACK) | (dark >= _CRACK)) | (strokes & band)
    tight = cracks | _shoulders(gray, band, cracks, corridor, min_span)
    tight = cv2.morphologyEx(tight.astype(np.uint8), cv2.MORPH_CLOSE, _kernel(5))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(tight, connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= _SPECK
    tight = keep[labels].astype(np.uint8)
    return cv2.dilate(tight, _kernel(5)).astype(bool) & band


def _shoulders(
    gray: np.ndarray,
    band: np.ndarray,
    cracks: np.ndarray,
    corridor: np.ndarray,
    min_span: int,
) -> np.ndarray:
    """Pixels beside a crack that run along it and differ from the band painted in from outside.

    An edge further out in the band, like the top of a hand under a fold, is part of the photo.
    """

    height, width = gray.shape
    factor = 4 if min(height, width) >= 1200 else 1
    holes: np.ndarray = band.astype(np.uint8) * 255
    if factor > 1:
        small = (max(1, width // factor), max(1, height // factor))
        low_gray = cv2.resize(gray, small, interpolation=cv2.INTER_AREA)
        holes = cv2.resize(holes, small, interpolation=cv2.INTER_AREA)
    else:
        low_gray = gray
    holes = cv2.dilate(np.where(holes > 0, 255, 0).astype(np.uint8), _kernel(3))
    background = cv2.inpaint(low_gray, holes, 3, cv2.INPAINT_TELEA)
    if factor > 1:
        background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    deviation = np.abs(gray.astype(np.int16) - background.astype(np.int16))
    # Away from the cracks, so a medal beside one is judged on its own shape.
    near = cv2.dilate(cracks.astype(np.uint8), _kernel(5)).astype(bool)
    lifted = (corridor & ~near & (deviation >= _DEVIATION)).astype(np.uint8)
    found = np.zeros(band.shape, dtype=bool)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(lifted, connectivity=8)
    for label in range(1, count):
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if max(w, h) < min_span:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        selected = labels[y : y + h, x : x + w] == label
        if _elongated(selected, min_span):
            found[y : y + h, x : x + w] |= selected
    return found


def _kernel(size: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _line_response(gray: np.ndarray, length: int) -> np.ndarray:
    response = np.zeros(gray.shape, dtype=np.uint8)
    for size in ((length, 1), (1, length)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, size)
        for kind in (cv2.MORPH_TOPHAT, cv2.MORPH_BLACKHAT):
            hat = cv2.morphologyEx(gray, kind, kernel)
            response = np.maximum(response, hat)
    return response


def _strokes(
    response: np.ndarray,
    level: int,
    max_radius: float,
    min_length: int,
) -> np.ndarray:
    strokes = np.where(response >= level, 255, 0).astype(np.uint8)
    if not strokes.any():
        return np.zeros(strokes.shape, dtype=bool)
    distance = cv2.distanceTransform(strokes, cv2.DIST_L2, 3)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(strokes, connectivity=8)
    kept = np.zeros(strokes.shape, dtype=bool)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_length:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        selected = labels[y : y + h, x : x + w] == label
        radius = distance[y : y + h, x : x + w][selected]
        if float(radius.max()) > max_radius:
            continue
        if not _elongated(selected, min_length):
            continue
        kept[y : y + h, x : x + w][selected] = True
    return kept


def _elongated(selected: np.ndarray, min_length: int) -> bool:
    """A stroke is long along one axis. A loop or a filled patch is not."""

    ys, xs = np.where(selected)
    if xs.size < min_length:
        return False
    coords = np.stack((xs.astype(np.float64), ys.astype(np.float64)), axis=1)
    centered = coords - coords.mean(axis=0)
    variance = np.linalg.eigvalsh((centered.T @ centered) / coords.shape[0])
    minor = float(np.sqrt(max(float(variance[0]), 0.0)))
    major = float(np.sqrt(max(float(variance[1]), 0.0)))
    if major * np.sqrt(12) < min_length:
        return False
    return major >= minor * 3


def _attach_fragments(seeds: np.ndarray, response: np.ndarray) -> np.ndarray:
    """Keep a short piece of a tear when it continues a stroke already accepted.

    A jagged tear breaks into pieces that are too short or too square to pass
    on their own. Pieces that wander off the stroke, and slivers on the border,
    stay out.
    """

    if not seeds.any():
        return seeds
    strokes = np.where(response >= _HAIRLINE, 255, 0).astype(np.uint8)
    if not strokes.any():
        return seeds
    thickness = cv2.distanceTransform(strokes, cv2.DIST_L2, 3)
    count, comps, stats, _centroids = cv2.connectedComponentsWithStats(strokes, connectivity=8)
    height, width = seeds.shape
    pieces: list[tuple[int, int, int, int, np.ndarray]] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 12:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        selected = comps[y : y + h, x : x + w] == label
        if float(thickness[y : y + h, x : x + w][selected].max()) > 4:
            continue
        on_border = x == 0 or y == 0 or x + w >= width or y + h >= height
        if on_border and min(w, h) <= 3:
            continue
        pieces.append((x, y, w, h, selected))
    grown = seeds
    for _step in range(4):
        extra = _fragments_along(grown, pieces)
        if not extra.any():
            break
        grown = grown | extra
    return grown


def _fragments_along(
    seeds: np.ndarray,
    pieces: list[tuple[int, int, int, int, np.ndarray]],
) -> np.ndarray:
    dist, labels = cv2.distanceTransformWithLabels(
        (~seeds).astype(np.uint8),
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    ys, xs = np.where(seeds)
    ids = labels[ys, xs]
    loc_y = np.zeros(int(ids.max()) + 1, np.int32)
    loc_x = np.zeros(int(ids.max()) + 1, np.int32)
    loc_y[ids] = ys
    loc_x[ids] = xs
    extra = np.zeros(seeds.shape, dtype=bool)
    for x, y, _w, _h, selected in pieces:
        local = dist[y : y + selected.shape[0], x : x + selected.shape[1]]
        gap = float(local[selected].min())
        if gap < 1 or gap > 40:
            continue
        best = int(np.flatnonzero(selected)[np.argmin(local[selected])])
        ly, lx = np.unravel_index(best, selected.shape)
        pix = int(labels[y + int(ly), x + int(lx)])
        if pix <= 0:
            continue
        direction = _axis_at(seeds, int(loc_x[pix]), int(loc_y[pix]))
        if direction is None:
            continue
        cys, cxs = np.where(selected)
        offset = np.array([float(cxs.mean()) + x - loc_x[pix], float(cys.mean()) + y - loc_y[pix]])
        norm = float(np.linalg.norm(offset))
        if norm < 1 or abs(float(np.dot(offset / norm, direction))) < 0.85:
            continue
        extra[y : y + selected.shape[0], x : x + selected.shape[1]][selected] = True
    return extra


def _axis_at(seeds: np.ndarray, x: int, y: int) -> np.ndarray | None:
    radius = 36
    y0, y1 = max(0, y - radius), min(seeds.shape[0], y + radius + 1)
    x0, x1 = max(0, x - radius), min(seeds.shape[1], x + radius + 1)
    ys, xs = np.where(seeds[y0:y1, x0:x1])
    if xs.size < 12:
        return None
    coords = np.stack((xs.astype(np.float64), ys.astype(np.float64)), axis=1)
    centered = coords - coords.mean(axis=0)
    values, vectors = np.linalg.eigh((centered.T @ centered) / coords.shape[0])
    minor = float(np.sqrt(max(float(values[0]), 0.0)))
    major = float(np.sqrt(max(float(values[1]), 0.0)))
    if major < minor * 2.2 or major < 6:
        return None
    return vectors[:, 1]


def _bridge(seeds: np.ndarray, broad: np.ndarray, *, search: int) -> np.ndarray:
    """Join pieces of one stroke across a faded gap, along rows and along columns."""

    mask = np.array(seeds, copy=True)
    _bridge_rows(mask, seeds, broad, search=search, square=True)
    # Transposed views, so a vertical crease is bridged by the same code and written back.
    _bridge_rows(mask.T, seeds.T, broad.T, search=search, square=False)
    return mask


def _bridge_rows(
    mask: np.ndarray,
    seeds: np.ndarray,
    broad: np.ndarray,
    *,
    search: int,
    square: bool,
) -> None:
    """Bridge strokes that lie along the rows. A stroke across them is left to the other pass.

    `square` decides which pass owns a piece as tall as it is wide, so it is used once.
    """

    max_gap = max(48, int(seeds.shape[1] * 0.08))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.ascontiguousarray(seeds, dtype=np.uint8), connectivity=8
    )
    spans: list[dict[str, int]] = []
    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if w < h or (w == h and not square):
            continue
        selected = labels[y : y + h, x : x + w] == label
        columns = np.flatnonzero(selected.any(axis=0))
        if columns.size == 0:
            continue
        left = int(columns[0])
        right = int(columns[-1])
        spans.append(
            {
                "x0": x + left,
                "x1": x + right,
                "y0": y + int(np.median(np.flatnonzero(selected[:, left]))),
                "y1": y + int(np.median(np.flatnonzero(selected[:, right]))),
            }
        )
    for span in spans:
        nxt = _continues(span, spans, max_gap)
        if nxt is not None:
            _paint_gap(mask, broad, span, nxt, search)


def _continues(
    span: dict[str, int],
    spans: list[dict[str, int]],
    max_gap: int,
) -> dict[str, int] | None:
    best: tuple[int, int, dict[str, int]] | None = None
    for other in spans:
        gap = other["x0"] - span["x1"] - 1
        if gap < 1 or gap > max_gap:
            continue
        drift = abs(span["y1"] - other["y0"])
        if drift > 14 + int(0.15 * gap):
            continue
        if best is None or gap < best[0] or (gap == best[0] and drift < best[1]):
            best = (gap, drift, other)
    return None if best is None else best[2]


def _paint_gap(
    mask: np.ndarray,
    broad: np.ndarray,
    left: dict[str, int],
    right: dict[str, int],
    search: int,
) -> None:
    gap = right["x0"] - left["x1"] - 1
    if gap < 1:
        return
    height = broad.shape[0]
    columns: list[tuple[int, int]] = []
    for index, x in enumerate(range(left["x1"] + 1, right["x0"])):
        predicted = int(round(left["y1"] + (right["y0"] - left["y1"]) * ((index + 1) / (gap + 1))))
        y0 = max(0, predicted - search)
        y1 = min(height, predicted + search + 1)
        column = broad[y0:y1, x]
        if column.size == 0 or int(column.max()) < _BRIDGE:
            continue
        columns.append((x, y0 + int(np.argmax(column))))
    if len(columns) / gap < 0.35:
        return
    floor = max(10, int(_BRIDGE * 0.55))
    for x, y in columns:
        for offset in range(-4, 5):
            yy = y + offset
            if 0 <= yy < height and int(broad[yy, x]) >= floor:
                mask[yy, x] = True


def _widen_creases(mask: np.ndarray, *, radius: int, min_span: int) -> np.ndarray:
    """A thick stroke that keeps going is a fold. Cover one solid band around it.

    Pieces of the same fold are joined across the gaps where the paper is pale and
    the stroke finder dropped them. A hairline stays narrow.
    """

    covered = np.array(mask, copy=True)
    height, width = mask.shape
    segments = _thick_runs(mask, min_span)
    _paint_bands(covered, [seg for seg in segments if seg[0] == "h"], radius, height, width, axis=0)
    _paint_bands(covered, [seg for seg in segments if seg[0] == "v"], radius, height, width, axis=1)
    return covered


def _thick_runs(mask: np.ndarray, min_span: int) -> list[tuple[str, dict[int, int]]]:
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    runs: list[tuple[str, dict[int, int]]] = []
    for label in range(1, count):
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        selected = labels[y : y + h, x : x + w] == label
        horizontal = w >= h
        if (w if horizontal else h) < min_span:
            continue
        centers: dict[int, int] = {}
        if horizontal:
            columns = np.flatnonzero(selected.any(axis=0))
            if columns.size == 0 or float(np.median(selected[:, columns].sum(axis=0))) < 8:
                continue
            for col in columns:
                centers[x + int(col)] = y + int(np.median(np.flatnonzero(selected[:, col])))
            runs.append(("h", centers))
        else:
            rows = np.flatnonzero(selected.any(axis=1))
            if rows.size == 0 or float(np.median(selected[rows].sum(axis=1))) < 8:
                continue
            for row in rows:
                centers[y + int(row)] = x + int(np.median(np.flatnonzero(selected[row])))
            runs.append(("v", centers))
    return runs


def _paint_bands(
    covered: np.ndarray,
    runs: list[tuple[str, dict[int, int]]],
    radius: int,
    height: int,
    width: int,
    *,
    axis: int,
) -> None:
    ordered = sorted((centers for _kind, centers in runs), key=lambda item: min(item))
    along = width if axis == 0 else height
    cross = height if axis == 0 else width
    max_gap = max(radius * 8, int(along * 0.1))
    drift_limit = max(28, radius // 2)
    chains: list[dict[int, int]] = []
    current: dict[int, int] | None = None
    for centers in ordered:
        if current is None:
            current = dict(centers)
            continue
        left = max(current)
        right = min(centers)
        gap = right - left - 1
        drift = abs(current[left] - centers[right])
        if gap < 1 or gap > max_gap or drift > drift_limit:
            chains.append(current)
            current = dict(centers)
            continue
        step = (centers[right] - current[left]) / (gap + 1)
        for index, pos in enumerate(range(left + 1, right)):
            current[pos] = int(round(current[left] + step * (index + 1)))
        current.update(centers)
    if current is not None:
        chains.append(current)
    for chain in chains:
        for pos, center in chain.items():
            start = max(0, center - radius)
            end = min(cross, center + radius + 1)
            if axis == 0:
                covered[start:end, pos] = True
            else:
                covered[pos, start:end] = True


def _cover_ridge(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Include the shoulder of a tear. A hairline is left narrow.

    A mark only grows when it is already wide. Hair strokes are thin, and
    widening those follows the surrounding hair.
    """

    if not mask.any():
        return mask
    short = min(gray.shape)
    reach = max(8, int(round(short * 0.004)))
    window = _odd(max(reach * 6 + 1, 31))
    background = cv2.medianBlur(gray, window)
    elevated = np.abs(gray.astype(np.int16) - background.astype(np.int16)) >= 14
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (reach * 2 + 1, reach * 2 + 1))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    grown = mask.copy()
    height, width = mask.shape
    for label in range(1, count):
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if min(w, h) < 24:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        y0, x0 = max(0, y - reach), max(0, x - reach)
        y1, x1 = min(height, y + h + reach), min(width, x + w + reach)
        local = np.zeros((y1 - y0, x1 - x0), np.uint8)
        patch = labels[y : y + h, x : x + w] == label
        local[y - y0 : y - y0 + h, x - x0 : x - x0 + w] = patch.astype(np.uint8)
        near = cv2.dilate(local, kernel).astype(bool)
        grown[y0:y1, x0:x1] |= near & elevated[y0:y1, x0:x1]
    # The brightest edge of a tear can sit a short way beside the detected core.
    edge = max(12, int(round(short * 0.017)))
    edge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (edge * 2 + 1, edge * 2 + 1))
    beside = cv2.dilate(grown.astype(np.uint8), edge_kernel).astype(bool)
    strong = np.abs(gray.astype(np.int16) - background) >= 36
    # Only a long piece running with the tear. An eye or a letter beside it stays out.
    edges = (beside & strong & ~grown).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(edges, 8)
    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        selected = labels[y : y + h, x : x + w] == label
        if _elongated(selected, edge * 2):
            grown[y : y + h, x : x + w] |= selected
    return grown


def _odd(value: float) -> int:
    number = int(round(value))
    return number if number % 2 else number + 1
