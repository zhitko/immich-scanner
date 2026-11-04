from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_services, get_session
from app.immich.gateway import ImmichError
from app.runtime import Services
from app.schemas import AlbumOut, ConnectionTest, SettingsOut, SettingsUpdate
from app.settings_store import ArchiveSettings, load_settings, save_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def read_settings(session: Session = Depends(get_session)) -> SettingsOut:
    return _out(load_settings(session))


@router.put("/settings", response_model=SettingsOut)
def write_settings(body: SettingsUpdate, session: Session = Depends(get_session)) -> SettingsOut:
    save_settings(session, _archive(body))
    return _out(load_settings(session))


@router.post("/settings/test", response_model=ConnectionTest)
def test_connection(
    body: SettingsUpdate,
    services: Services = Depends(get_services),
) -> ConnectionTest:
    gateway = _gateway(services, body.immich_base_url, body.immich_api_key)
    try:
        version = gateway.server_version()
        albums = gateway.list_albums()
    except ImmichError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        gateway.close()
    return ConnectionTest(ok=True, version=version, album_count=len(albums))


@router.get("/immich/albums", response_model=list[AlbumOut])
def list_albums(
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> list[AlbumOut]:
    stored = load_settings(session)
    gateway = _gateway(services, stored.immich_base_url, stored.immich_api_key)
    try:
        albums = gateway.list_albums()
    except ImmichError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        gateway.close()
    return [
        AlbumOut(id=album.id, name=album.name, asset_count=album.asset_count) for album in albums
    ]


def _gateway(services: Services, url: str, api_key: str):
    try:
        return services.build_gateway(url, api_key)
    except ImmichError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _archive(body: SettingsUpdate) -> ArchiveSettings:
    return ArchiveSettings(
        immich_base_url=body.immich_base_url.strip(),
        immich_api_key=body.immich_api_key.strip(),
        output_format=body.output_format,
        jpeg_quality=body.jpeg_quality,
        default_album_id=body.default_album_id.strip(),
        device_name=body.device_name.strip(),
        resolution_dpi=body.resolution_dpi,
        scan_format=body.scan_format,
        scan_mode=body.scan_mode,
        width_mm=body.width_mm,
        height_mm=body.height_mm,
    )


def _out(settings: ArchiveSettings) -> SettingsOut:
    return SettingsOut(
        immich_base_url=settings.immich_base_url,
        immich_api_key=settings.immich_api_key,
        output_format=settings.output_format,  # type: ignore[arg-type]
        jpeg_quality=settings.jpeg_quality,
        default_album_id=settings.default_album_id,
        device_name=settings.device_name,
        resolution_dpi=settings.resolution_dpi,
        scan_format=settings.scan_format,  # type: ignore[arg-type]
        scan_mode=settings.scan_mode,  # type: ignore[arg-type]
        width_mm=settings.width_mm,
        height_mm=settings.height_mm,
    )
