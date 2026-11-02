from pathlib import Path

import httpx


class UploadError(Exception):
    """The archive server rejected the scan or could not be reached."""


class ScanUploader:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def upload(
        self,
        *,
        server_url: str,
        api_token: str,
        image_path: Path,
        dpi: int,
        device_name: str,
        image_format: str,
    ) -> str:
        url = server_url.rstrip("/") + "/api/ingest/scans"
        content_type = "image/png" if image_format == "png" else "image/tiff"
        try:
            with self._open() as client, image_path.open("rb") as handle:
                response = client.post(
                    url,
                    headers={"X-Scanner-Token": api_token},
                    data={
                        "dpi": str(dpi),
                        "device_name": device_name,
                        "filename": image_path.name,
                    },
                    files={"file": (image_path.name, handle, content_type)},
                )
        except httpx.HTTPError as exc:
            raise UploadError(f"could not reach the server: {exc}") from exc
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise UploadError(f"server returned {response.status_code}: {detail}")
        payload = response.json()
        scan_id = payload.get("scan_id")
        if not isinstance(scan_id, str) or not scan_id:
            raise UploadError("server response did not include scan_id")
        return scan_id

    def probe(self, server_url: str) -> None:
        url = server_url.rstrip("/") + "/api/health"
        try:
            with self._open(timeout=5) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise UploadError(str(exc)) from exc
        if response.status_code != 200:
            raise UploadError(f"health check returned {response.status_code}")

    def _open(self, timeout: float = 300) -> httpx.Client:
        if self._client is not None:
            return _BorrowedClient(self._client)
        return httpx.Client(timeout=timeout)


class _BorrowedClient:
    """Allow `with` around an injected client without closing it."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __enter__(self) -> httpx.Client:
        return self._client

    def __exit__(self, *_exc: object) -> None:
        return None


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "request failed"
    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        return str(detail)
    return response.text.strip() or "request failed"
