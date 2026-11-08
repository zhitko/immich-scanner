"""Local, versioned visual descriptors for human-reviewed series suggestions."""

import hashlib
import json
import logging

import cv2
import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.imaging.crop import crop_rotated_rect, resize_max_edge
from app.imaging.io import load_rgb
from app.models import Job, PhotoIndex, PhotoMatch, Region, Scan
from app.retouch.options import geometry_signature
from app.runtime import Services
from app.schemas import MatchField

logger = logging.getLogger(__name__)
INDEX_VERSION = "visual-series-v1"
MAX_MATCHES_PER_PHOTO = 3
FIELDS: tuple[MatchField, ...] = (
    "taken_at",
    "description",
    "album_id",
    "location",
    "is_favorite",
    "rating",
    "visibility",
)


def has_field(region: Region, field: MatchField) -> bool:
    if field == "location":
        return region.latitude is not None and region.longitude is not None
    value = getattr(region, field)
    return (
        bool(value.strip()) if isinstance(value, str) else value is not None and value is not False
    )


def available_fields(source: Region, target: Region) -> list[MatchField]:
    return [
        field
        for field in FIELDS
        if has_field(source, field)
        and not has_field(target, field)
        and (field != "location" or (target.latitude is None and target.longitude is None))
    ]


def index_signature(scan: Scan, region: Region) -> str:
    value = f"{INDEX_VERSION}|{scan.original_path}|{geometry_signature(region)}"
    return hashlib.sha256(value.encode()).hexdigest()


def visual_features(image: np.ndarray) -> np.ndarray:
    """Four rotations of color, coarse structure and spatial edge descriptors.

    These are visual hints, not semantic embeddings or date confidence. Cropping
    the outer 5% reduces the influence of print borders and scanner backgrounds.
    Blank images are excluded instead of suggesting every other blank print.
    """
    height, width = image.shape[:2]
    y, x = max(1, height // 20), max(1, width // 20)
    if height > 2 * y and width > 2 * x:
        image = image[y:-y, x:-x]
    image = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    if float(gray.std()) < 3:
        raise ValueError("Not enough visual detail to match this photo")
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    color = np.concatenate(
        [np.histogram(lab[:, :, c], bins=32, range=(0, 256))[0] for c in range(3)]
    ).astype(np.float32)
    color = np.sqrt(color / max(float(color.sum()), 1))
    vectors = []
    for turns in range(4):
        rotated = np.ascontiguousarray(np.rot90(gray, turns))
        structure = cv2.resize(rotated, (16, 16), interpolation=cv2.INTER_AREA).flatten()
        structure -= structure.mean()
        structure /= max(float(np.linalg.norm(structure)), 1e-6)
        gx = cv2.Sobel(rotated, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(rotated, cv2.CV_32F, 0, 1)
        magnitude, angle = cv2.cartToPolar(gx, gy)
        bins = (angle * (8 / (2 * np.pi))).astype(int) % 8
        edges = np.concatenate(
            [
                np.bincount(
                    bins[y : y + 16, x : x + 16].flatten(),
                    weights=magnitude[y : y + 16, x : x + 16].flatten(),
                    minlength=8,
                )
                for y in range(0, 64, 16)
                for x in range(0, 64, 16)
            ]
        ).astype(np.float32)
        edges = np.sqrt(edges)
        edges /= max(float(np.linalg.norm(edges)), 1e-6)
        vector = np.concatenate(
            [structure * np.sqrt(0.45), color * np.sqrt(0.35), edges * np.sqrt(0.20)]
        ).astype("<f4")
        vector /= max(float(np.linalg.norm(vector)), 1e-6)
        vectors.append(vector)
    return np.stack(vectors)


def handle_matching(session: Session, job: Job, services: Services) -> None:
    payload = json.loads(job.payload)
    minimum_score = float(payload.get("minimum_score", 0.82))
    rows = session.execute(
        select(Region, Scan)
        .join(Scan, Region.scan_id == Scan.id)
        .order_by(Scan.id, Region.position, Region.id)
    ).all()
    progress = dict(
        total=len(rows),
        processed=0,
        indexed=0,
        reused=0,
        skipped=0,
        pairs=0,
        phase="indexing",
        warnings=[],
    )
    pending: list[dict] = []
    skipped: list[str] = []

    def save_progress() -> None:
        # Keep decoding/scoring outside the writer lock. Recheck a crop before
        # caching it: editing or deleting photos is allowed while matching runs.
        session.execute(update(Job).where(Job.id == job.id).values(payload=Job.payload))
        if pending:
            current = {
                region.id: (region, scan)
                for region, scan in session.execute(
                    select(Region, Scan)
                    .join(Scan, Region.scan_id == Scan.id)
                    .where(Region.id.in_([item["region_id"] for item in pending]))
                    .execution_options(populate_existing=True)
                )
            }
            for item in pending:
                pair = current.get(item["region_id"])
                if pair is None:
                    continue
                region, scan = pair
                if scan.files_deleted or index_signature(scan, region) != item["signature"]:
                    continue
                statement = insert(PhotoIndex).values(**item)
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[PhotoIndex.region_id],
                        set_={
                            "signature": statement.excluded.signature,
                            "features": statement.excluded.features,
                        },
                    )
                )
            pending.clear()
        if skipped:
            session.execute(delete(PhotoIndex).where(PhotoIndex.region_id.in_(skipped)))
            skipped.clear()
        job.payload = json.dumps({"minimum_score": minimum_score, **progress})
        session.commit()

    save_progress()
    indexed: list[tuple[Region, str, np.ndarray]] = []
    original_path = None
    original = None
    for region, scan in rows:
        signature = index_signature(scan, region)
        cached = session.execute(
            select(PhotoIndex.signature, PhotoIndex.features).where(
                PhotoIndex.region_id == region.id
            )
        ).first()
        try:
            if scan.files_deleted or not scan.original_path:
                raise FileNotFoundError("Local scan files were removed")
            if not services.storage.absolute(scan.original_path).is_file():
                raise FileNotFoundError("Local scan file is missing")
            if cached and cached.signature == signature:
                features = np.frombuffer(cached.features, dtype="<f4").reshape(4, -1)
                progress["reused"] += 1
            else:
                if original_path != scan.original_path:
                    original, _ = load_rgb(services.storage.absolute(scan.original_path))
                    original_path = scan.original_path
                crop = crop_rotated_rect(
                    original,
                    region.center_x,
                    region.center_y,
                    region.width,
                    region.height,
                    region.angle_deg,
                )
                features = visual_features(resize_max_edge(crop, 1000))
                pending.append(
                    dict(region_id=region.id, signature=signature, features=features.tobytes())
                )
            indexed.append((region, signature, features))
            progress["indexed"] += 1
        except (OSError, ValueError, cv2.error) as exc:
            progress["skipped"] += 1
            if cached:
                skipped.append(region.id)
            if len(progress["warnings"]) < 5:
                progress["warnings"].append(f"Photo {region.id[:8]}: {exc}")
            logger.info("Skipping matching index for %s: %s", region.id, exc)
        progress["processed"] += 1
        if progress["processed"] % 10 == 0:
            save_progress()
    del original
    progress["phase"] = "matching"
    progress["processed"] = 0
    save_progress()
    sources = [item for item in indexed if any(has_field(item[0], field) for field in FIELDS)]
    dismissed = set(
        session.execute(
            select(PhotoMatch.source_id, PhotoMatch.target_id).where(PhotoMatch.dismissed.is_(True))
        ).all()
    )
    matches: list[PhotoMatch] = []
    if sources:
        # O(N * sources) work, but no NxN matrix: score just one target at a time.
        matrix = np.stack([item[2] for item in sources])
        for target, target_signature, target_features in indexed:
            scores = (matrix @ target_features[0]).max(axis=1)
            count = 0
            for index in np.argsort(-scores, kind="stable"):
                score = float(np.clip(scores[index], 0, 1))
                if score < minimum_score:
                    break
                source, source_signature, _ = sources[index]
                if source.id == target.id or (source.id, target.id) in dismissed:
                    continue
                if not available_fields(source, target):
                    continue
                matches.append(
                    PhotoMatch(
                        source_id=source.id,
                        target_id=target.id,
                        score=score,
                        source_signature=source_signature,
                        target_signature=target_signature,
                    )
                )
                count += 1
                if count == MAX_MATCHES_PER_PHOTO:
                    break
            progress["processed"] += 1
            if progress["processed"] % 100 == 0:
                save_progress()
    # Publish a whole run together; a failed run leaves the previous results intact.
    # This delete takes the writer lock before rechecking deletions/dismissals.
    session.execute(delete(PhotoMatch).where(PhotoMatch.dismissed.is_(False)))
    current = {
        region.id: (region, scan)
        for region, scan in session.execute(
            select(Region, Scan)
            .join(Scan, Region.scan_id == Scan.id)
            .where(Scan.files_deleted.is_(False), Scan.original_path != "")
            .execution_options(populate_existing=True)
        )
    }
    signatures = {
        region_id: index_signature(scan, region) for region_id, (region, scan) in current.items()
    }
    dismissed = set(
        session.execute(
            select(PhotoMatch.source_id, PhotoMatch.target_id).where(PhotoMatch.dismissed.is_(True))
        ).all()
    )
    matches = [
        match
        for match in matches
        if signatures.get(match.source_id) == match.source_signature
        and signatures.get(match.target_id) == match.target_signature
        and (match.source_id, match.target_id) not in dismissed
        and available_fields(current[match.source_id][0], current[match.target_id][0])
    ]
    session.add_all(matches)
    progress.update(phase="finished", processed=len(indexed), pairs=len(matches))
    save_progress()
