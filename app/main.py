from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import jobs, matching, photos, retouch, scans, statistics, uploads
from app.api import scanner as scanner_api
from app.api import settings as settings_api
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.detection.opencv_detector import OpenCvPhotoDetector
from app.immich.client import ImmichClient
from app.jobs.worker import JobWorker
from app.migrate import upgrade_database
from app.retouch.engine import OnnxRetoucher
from app.runtime import Services
from app.scanner.factory import build_scanner
from app.scanning import BedScan
from app.settings_store import seed_settings
from app.storage import Storage


def create_app(settings: Settings | None = None) -> FastAPI:
    process_settings = settings or get_settings()
    process_settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(process_settings.sqlite_url())
    engine = make_engine(process_settings.sqlite_url())
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        seed_settings(session, process_settings)
        session.commit()
    services = Services(
        settings=process_settings,
        engine=engine,
        session_factory=session_factory,
        storage=Storage(process_settings.data_dir),
        detector=OpenCvPhotoDetector(),
        retoucher=OnnxRetoucher(
            process_settings.resolved_models_dir(),
            execution=process_settings.retouch_execution,
            openvino_device=process_settings.retouch_openvino_device,
        ),
        build_gateway=lambda url, key: ImmichClient(url, key),
    )
    worker = JobWorker(services)
    scanning = BedScan(services, build_scanner(process_settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.services.settings.worker_enabled:
            app.state.worker.start()
        yield
        app.state.worker.stop()

    app = FastAPI(title="immich-scanner", version="0.1.0", lifespan=lifespan)
    app.state.services = services
    app.state.worker = worker
    app.state.scanning = scanning
    app.include_router(scanner_api.router, prefix="/api")
    app.include_router(scans.router, prefix="/api")
    app.include_router(photos.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(retouch.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")
    app.include_router(statistics.router, prefix="/api")
    app.include_router(matching.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_interface(app, process_settings.static_dir)
    return app


def _mount_interface(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        return
    app.mount("/", SpaFiles(directory=static_dir), name="ui")


class SpaFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            response = await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as exc:
            if exc.status_code != 404:
                raise
            path = "index.html"
            response = await super().get_response(path, scope)
        if path in ("", ".", "index.html"):
            # The shell names the hashed bundles, so it must be revalidated after each build.
            response.headers["Cache-Control"] = "no-cache"
        return response
