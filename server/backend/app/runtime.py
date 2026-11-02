from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.detection.base import PhotoDetector
from app.immich.gateway import ImmichGateway
from app.storage import Storage


@dataclass
class Services:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    storage: Storage
    detector: PhotoDetector
    build_gateway: Callable[[str, str], ImmichGateway]
