import shutil
from pathlib import Path


class Storage:
    """Files live under the data volume. The database stores paths relative to it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def absolute(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("path escapes the data directory")
        return path

    def scan_directory(self, scan_id: str) -> Path:
        path = self.absolute(f"scans/{scan_id}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def remove_tree(self, scan_id: str) -> None:
        target = self.root / "scans" / scan_id
        if target.exists():
            shutil.rmtree(target)
