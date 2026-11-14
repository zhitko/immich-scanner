from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_services, get_session
from app.clock import utcnow
from app.jobs.queue import enqueue_job
from app.retouch.batch import bulk_candidates
from app.retouch.catalog import CATALOG, ModelSpec, specs_for
from app.retouch.fetch import FetchError, download, inspect_file, model_actions, progress_for
from app.runtime import Services
from app.schemas import (
    BulkRetouchRequest,
    BulkRetouchSummary,
    ModelFetch,
    ModelProgress,
    RetouchModelOut,
)

router = APIRouter(prefix="/retouch", tags=["retouch"])


@router.get("/bulk", response_model=BulkRetouchSummary)
def preview_bulk_retouch(
    state: Literal["open", "uploaded", "all"] = "all",
    include_retouched: bool = False,
    session: Session = Depends(get_session),
) -> BulkRetouchSummary:
    summary = BulkRetouchSummary()
    for _region in bulk_candidates(session, state, include_retouched, summary):
        pass
    return summary


@router.post("/bulk", response_model=BulkRetouchSummary, status_code=202)
def run_bulk_retouch(
    body: BulkRetouchRequest,
    session: Session = Depends(get_session),
    services: Services = Depends(get_services),
) -> BulkRetouchSummary:
    choice = body.choice
    directory = services.settings.resolved_models_dir()
    missing = [
        filename
        for spec in specs_for(
            upscale=choice.upscale,
            denoise=choice.denoise,
            faces=choice.faces,
            colorize=choice.colorize,
            scratches=choice.scratches,
            light_corners=choice.light_corners,
        )
        for filename in spec.filenames()
        if not (directory / filename).is_file()
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing weights: {', '.join(missing)}. Download them under Settings first.",
        )
    summary = BulkRetouchSummary()
    for region in bulk_candidates(session, body.state, body.include_retouched, summary):
        for name, value in choice.model_dump().items():
            setattr(region, f"retouch_{name}", value)
        enqueue_job(
            session,
            job_type="retouch",
            scan_id=region.scan_id,
            region_id=region.id,
            payload={"scan_id": region.scan_id, "region_id": region.id},
        )
        region.retouch_status = "queued"
        region.retouch_error = None
        region.updated_at = utcnow()
        summary.queued += 1
    session.flush()
    return summary


@router.get("/models", response_model=list[RetouchModelOut])
def list_models(services: Services = Depends(get_services)) -> list[RetouchModelOut]:
    directory = services.settings.resolved_models_dir()
    return [_out(spec, directory) for spec in CATALOG.values()]


@router.post("/models/{model_id}", response_model=RetouchModelOut)
def fetch_model(
    model_id: str,
    body: ModelFetch,
    services: Services = Depends(get_services),
) -> RetouchModelOut:
    spec = CATALOG.get(model_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown model.")
    if not body.accept:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Read the {spec.license_id} license for {spec.filename} before downloading it."
            ),
        )
    directory = services.settings.resolved_models_dir()
    try:
        download(spec, directory / spec.filename, accepted={spec.id}, force=body.force)
    except FetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not download {spec.filename}.",
        ) from exc
    return _out(spec, directory)


def _out(spec: ModelSpec, directory: Path) -> RetouchModelOut:
    state = inspect_file(spec, directory)
    can_download, can_update, can_redownload = model_actions(spec, state)
    current = progress_for(spec.id)
    return RetouchModelOut(
        id=spec.id,
        purpose=spec.purpose,
        version=spec.version,
        license_id=spec.license_id,
        license_summary=spec.license_summary,
        source_url=spec.source_url,
        filename=spec.filename,
        present=state.present,
        matches_pin=state.matches_pin,
        automatic_download=spec.download_url is not None,
        can_download=can_download,
        can_update=can_update,
        can_redownload=can_redownload,
        size_bytes=state.size_bytes,
        progress=None
        if current is None
        else ModelProgress(received=current.received, total=current.total, phase=current.phase),
    )
