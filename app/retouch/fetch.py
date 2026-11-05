import argparse
import hashlib
import os
import threading
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from app.config import get_settings
from app.retouch.catalog import CATALOG, ModelSpec


class FetchError(Exception):
    pass


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _destination_lock(destination: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(destination.name)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[destination.name] = lock
        return lock


@dataclass(frozen=True)
class ModelFile:
    present: bool
    matches_pin: bool | None
    size_bytes: int | None


def inspect_file(spec: ModelSpec, directory: Path) -> ModelFile:
    path = directory / spec.filename
    paths = [directory / name for name in spec.filenames()]
    if not all(item.is_file() for item in paths):
        return ModelFile(False, None, None)
    size = sum(item.stat().st_size for item in paths)
    if spec.sha256 is None and not spec.extra:
        return ModelFile(True, None, size)
    matches = spec.sha256 is None or _hash(path) == spec.sha256
    for item in spec.extra:
        companion = directory / item.filename
        matches = matches and companion.is_file() and _hash(companion) == item.sha256
    return ModelFile(True, matches, size)


def model_actions(spec: ModelSpec, state: ModelFile) -> tuple[bool, bool, bool]:
    """Download, update, or redownload.

    A missing file can be downloaded. A pinned file that does not match can be
    updated. A file that is already present and current can be downloaded again.
    """
    if spec.download_url is None:
        return False, False, False
    if not state.present:
        return True, False, False
    if state.matches_pin is False:
        return False, True, False
    return False, False, True


@dataclass(frozen=True)
class DownloadProgress:
    received: int
    total: int | None
    phase: Literal["downloading", "installing"]


_PROGRESS: dict[str, DownloadProgress] = {}
_PROGRESS_GUARD = threading.Lock()


def progress_for(model_id: str) -> DownloadProgress | None:
    with _PROGRESS_GUARD:
        return _PROGRESS.get(model_id)


def _publish(
    model_id: str,
    received: int,
    total: int | None,
    phase: Literal["downloading", "installing"],
) -> None:
    with _PROGRESS_GUARD:
        _PROGRESS[model_id] = DownloadProgress(received, total, phase)


def _clear_progress(model_id: str) -> None:
    with _PROGRESS_GUARD:
        _PROGRESS.pop(model_id, None)


def license_text(spec: ModelSpec) -> str:
    download = "This command can download it after you accept the license."
    if spec.download_url is None:
        download = "This command does not download it. Place the ONNX file yourself."
    return (
        f"{spec.filename}\n"
        f"  {spec.purpose}\n"
        f"  License: {spec.license_id}\n"
        f"  {spec.license_summary}\n"
        f"  Source: {spec.source_url}\n"
        f"  {download}"
    )


def prepare_download(spec: ModelSpec, *, accepted: set[str]) -> str:
    if spec.id not in accepted:
        raise FetchError(
            f"Read the {spec.license_id} license for {spec.filename} and pass --accept {spec.id}."
        )
    if spec.download_url is None:
        raise FetchError(
            f"{spec.filename} is not downloaded by this app. {spec.license_summary} "
            "Place the ONNX file in the models directory yourself."
        )
    return spec.download_url


def download(
    spec: ModelSpec,
    destination: Path,
    *,
    accepted: set[str],
    force: bool = False,
) -> None:
    prepare_download(spec, accepted=accepted)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _destination_lock(destination):
        if not force and inspect_file(spec, destination.parent).matches_pin is True:
            return
        # The archive must not use the ".part" name. Extracting the ONNX writes that
        # same path, and truncating it corrupts the zip this function still has open.
        suffix = ".archive" if spec.archive_name else ".part"
        temporary = destination.with_name(destination.name + suffix)
        assert spec.download_url is not None
        try:
            _publish(spec.id, 0, None, "downloading")
            with httpx.stream(
                "GET",
                spec.download_url,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, read=600.0),
            ) as response:
                response.raise_for_status()
                raw_length = response.headers.get("content-length")
                total = (
                    int(raw_length)
                    if isinstance(raw_length, str) and raw_length.isdigit()
                    else None
                )
                received = 0
                _publish(spec.id, received, total, "downloading")
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        received += len(chunk)
                        _publish(spec.id, received, total, "downloading")
            _publish(spec.id, received, total, "installing")
            if spec.archive_name:
                install_archive(spec, temporary, destination)
            else:
                observed = _hash(temporary)
                if spec.sha256 and observed != spec.sha256:
                    raise FetchError(f"{spec.filename} checksum did not match the pinned hash.")
                os.replace(temporary, destination)
        except FetchError:
            temporary.unlink(missing_ok=True)
            raise
        except (OSError, zipfile.BadZipFile, zlib.error) as exc:
            temporary.unlink(missing_ok=True)
            raise FetchError(f"{spec.filename} download was incomplete.") from exc
        finally:
            _clear_progress(spec.id)
        temporary.unlink(missing_ok=True)


def install_archive(spec: ModelSpec, archive_path: Path, destination: Path) -> None:
    written: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if spec.archive_name is None:
                raise FetchError(f"{spec.filename} has no archive entry.")
            _extract_member(archive, spec.archive_name, destination, spec.sha256)
            written.append(destination)
            for extra in spec.extra:
                path = destination.parent / extra.filename
                _extract_member(archive, extra.archive_name, path, extra.sha256)
                written.append(path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def _extract_member(
    archive: zipfile.ZipFile, name: str, destination: Path, expected: str | None
) -> None:
    try:
        member = archive.getinfo(name)
    except KeyError as exc:
        raise FetchError(f"{destination.name} was not in the download.") from exc
    temporary = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    try:
        with archive.open(member) as source, temporary.open("wb") as handle:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                digest.update(chunk)
                handle.write(chunk)
        if expected and digest.hexdigest() != expected:
            raise FetchError(f"{destination.name} checksum did not match the pinned hash.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show retouch model licenses and download weights."
    )
    parser.add_argument(
        "--accept",
        action="append",
        default=[],
        help="Model id whose license you have read. Repeat for more than one.",
    )
    parser.add_argument("--models-dir", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download again even when the file already matches.",
    )
    args = parser.parse_args(argv)
    directory = args.models_dir or get_settings().resolved_models_dir()
    accepted = set(args.accept)
    unknown = sorted(accepted - set(CATALOG))
    if unknown:
        print(f"Unknown model id: {', '.join(unknown)}")
        return 2
    print(f"Models directory: {directory}")
    print("Weights are not part of the git checkout.")
    exit_code = 0
    for spec in CATALOG.values():
        state = inspect_file(spec, directory)
        print()
        print(license_text(spec))
        print(f"  Version: {spec.version}")
        if not state.present:
            print("  Present: no")
        elif state.matches_pin is False:
            print("  Present: a different file")
        else:
            print("  Present: yes")
        if spec.id not in accepted:
            continue
        try:
            download(spec, directory / spec.filename, accepted=accepted, force=args.force)
        except FetchError as exc:
            print(f"  {exc}")
            exit_code = 2
        else:
            print(f"  Saved {directory / spec.filename}")
    return exit_code


_HASHES: dict[Path, tuple[tuple[int, int], str]] = {}
_HASHES_GUARD = threading.Lock()


def _hash(path: Path) -> str:
    """SHA-256 in chunks, reused until the file's size or mtime changes."""

    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _HASHES_GUARD:
        cached = _HASHES.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    with _HASHES_GUARD:
        _HASHES[path] = (stamp, value)
    return value
