from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.scanner.factory import build_scanner
from app.schemas import ClientSettings, ClientSettingsUpdate, ScanAccepted
from app.service import AgentService
from app.state_store import StateStore
from app.uploader import ScanUploader

_STATIC = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, service: AgentService | None = None) -> FastAPI:
    process_settings = settings or get_settings()
    app = FastAPI(title="immich-scanner client", version="0.1.0")
    if service is None:
        seed = ClientSettings(
            server_url=process_settings.server_url,
            api_token=process_settings.api_token,
            resolution_dpi=process_settings.resolution_dpi,
            image_format=process_settings.image_format,
        )
        store = StateStore(process_settings.data_dir, seed)
        service = AgentService(
            store,
            build_scanner(process_settings),
            ScanUploader(),
            process_settings.data_dir,
        )
    app.state.service = service

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        return app.state.service.status()

    @app.get("/api/settings")
    def read_settings():
        return app.state.service.settings()

    @app.put("/api/settings")
    def write_settings(body: ClientSettingsUpdate):
        return app.state.service.update_settings(body.to_settings())

    @app.post("/api/scan", response_model=ScanAccepted, status_code=202)
    def scan() -> ScanAccepted:
        try:
            app.state.service.start_scan()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ScanAccepted()

    if _STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(_STATIC / "index.html")

    return app
