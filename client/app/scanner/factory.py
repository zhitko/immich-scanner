from app.config import Settings
from app.scanner.base import Scanner
from app.scanner.fake import FakeScanner
from app.scanner.sane import SaneScanner


def build_scanner(settings: Settings) -> Scanner:
    if settings.scanner_backend == "fake":
        return FakeScanner()
    return SaneScanner()
