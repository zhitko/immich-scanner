from fastapi import APIRouter, HTTPException, Request

from app.schemas import ScannerStatusOut, ScanStarted

router = APIRouter(tags=["scanner"])


@router.get("/scanner", response_model=ScannerStatusOut)
def scanner_status(request: Request) -> ScannerStatusOut:
    return request.app.state.scanning.status()


@router.post("/scanner/scan", response_model=ScanStarted, status_code=202)
def start_scan(request: Request) -> ScanStarted:
    try:
        request.app.state.scanning.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ScanStarted()
