# immich-scanner

Scan several physical photos at once on a flatbed, separate them, review the crops in a browser, and upload each photo to a self-hosted [Immich](https://immich.app) album.

The app runs on the laptop that owns the scanner. It captures the bed, detects the prints, and uploads the crops to Immich. Immich itself stays wherever it already runs.

```
laptop (USB scanner)
  scan the bed → detect and review → upload each crop to Immich
```

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
```

The desk is at `http://127.0.0.1:8080`. Original scans, crops, and the SQLite database stay in the `data/` folder on the host, mounted at `/data` in the container.

### Without a scanner or a real Immich

```bash
# .env
SCANNER_BACKEND=fake
IMMICH_BASE_URL=http://mock-immich:3001
IMMICH_API_KEY=dev-key

docker compose --profile mock up --build
```

The mock speaks the small part of the Immich API this project uses (version, albums, asset upload, metadata update, album membership). It forgets everything when the container stops.

`SCANNER_BACKEND=fake` returns the same three-print bed every time, so detection and review can be exercised with no USB device. The backend is chosen at startup. Resolution, file format, and the scan window are edited on the settings page, and that page wins over the environment after the first save.

## USB scanner

The expected device is a Canon CanoScan LiDE 700F (`04a9:1907`), driven by SANE's genesys backend through `scanimage`. The image installs `sane-utils` and `libsane1`. The compose file starts the container privileged and bind-mounts `/dev/bus/usb`, and the process runs as root so it can open the device node.

On the host, a udev rule keeps the node usable after replug:

```
# /etc/udev/rules.d/49-canoscan-lide-700f.rules
SUBSYSTEM=="usb", ATTRS{idVendor}=="04a9", ATTRS{idProduct}=="1907", MODE="0666"
```

Then `sudo udevadm control --reload-rules && sudo udevadm trigger`. Unplug and replug the scanner, and confirm the host sees it:

```bash
scanimage -L
# device `genesys:libusb:001:00N' is a Canon LiDE 700F flatbed scanner
```

The default scan is the full bed: `scanimage` is called without `-x` or `-y`, so the backend's own scan area is used (about 216×297 mm on this model). Resolution defaults to 300 dpi and the file is a lossless TIFF. PNG and a smaller window, in millimetres, are available in settings. The source is left at the backend default, which is the flatbed rather than the transparency unit.

## Run from a checkout

Python 3.12 and Node 22.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# API, with the fake scanner, on port 8000
SCANNER_BACKEND=fake DATA_DIR=./data python -m app

# mock Immich, optional, on port 3001
python -m mock_immich

# review UI during development (proxies /api to port 8000)
cd frontend && npm ci && npm start
```

To serve the built UI from the API instead of `ng serve`, run `npm run build` in `frontend` and start the API with `STATIC_DIR` pointed at `frontend/dist/immich-scanner-ui`.

## Review UI

The desk is one Angular app:

- **Waiting** shows whether the scanner is reachable and scans the bed, with the elapsed time while it runs. "Open for review when done" jumps straight to the new scan. The list holds scans that are not fully uploaded and shows which ones are still being detected.
- Open a scan to see the bed with the detected regions drawn on top. Drag a region to move it, drag a corner to resize it, and drag the round handle to rotate it (Shift snaps to 15°). Drag on an empty part of the bed to outline a photo the detector missed. Detection again replaces only regions that have not been uploaded, and skips photos that are already uploaded.
- Each photo has a date taken, description, album, location, favorite flag, rating, and visibility. "Save locally" writes those details on this computer only. "Copy to all photos" copies the date, album, and location to the rest of the scan. Pasting `lat, lon` into the latitude field fills both. Unsaved details are saved locally before switching photos or uploading. Rotate by 90° either way when a print is sideways. The crop preview is the straightened photo.
- Keyboard: <kbd>←</kbd>/<kbd>→</kbd> switch photos, <kbd>R</kbd>/<kbd>Shift</kbd>+<kbd>R</kbd> rotate, <kbd>Delete</kbd> removes, <kbd>Ctrl</kbd>+<kbd>S</kbd> saves locally.
- **Upload to Immich**, on the open photo, writes a full-resolution JPEG (quality from settings, default 95, 4:4:4) or a PNG, then creates the Immich asset, adds it to the album, and updates the metadata. The toolbar button does the same for every photo that still needs an upload. A failed photo can be retried. If the crop changed after a successful upload, the next upload creates a new asset and leaves the previous one in Immich. The date is written into EXIF at upload time.
- **Uploaded** keeps the history, including Immich asset ids, and can delete the original scan file to free disk space.
- **Jobs** shows queued, running, finished, and failed detection and upload work.
- **Settings** stores the scanner window and the Immich URL and API key, tests the connection, and lists albums.

The API is not authenticated. Keep it on the laptop.

The Immich API key needs `asset.upload`, `asset.update`, `album.read`, and `albumAsset.create`.

## How detection and uploads run

A scan writes the bed into the data directory and queues detection. Jobs live in the same SQLite database as the scans (`jobs` table, WAL). One worker thread in the API process claims the oldest queued job. A job left in `running` after a crash is queued again on startup. Redis or Celery would only add another service for a laptop that already persists everything in SQLite.

Detection downscales the bed, flood-fills whichever lid color is on the border, and turns the remaining contours into minimum-area rectangles. Each rectangle is expressed with its smallest tilt (within ±45°), so a landscape print stays landscape whatever angle convention the installed OpenCV uses. Specks and thin non-rectangular shapes, such as an edge shadow, are ignored.

The scanner is opened by one process at a time. Device checks and scans share a lock, status polls answer from the last check while the device is in use, and a scan that hits "Device busy" is retried a few times. The close kernel stays smaller than a 5 mm gap so neighbouring prints are not merged. The detector is the `PhotoDetector` protocol; `OpenCvPhotoDetector` is the implementation used by the app.

## Immich

The client targets the [v3.3.5 OpenAPI spec](https://github.com/immich-app/immich/blob/v3.3.5/open-api/immich-openapi-specs.json). Calls are under `/api` with the `x-api-key` header.

| Step | Request |
| --- | --- |
| Connection test | `GET /api/server/version`, `GET /api/albums` |
| Create asset | `POST /api/assets` multipart `assetData`, `fileCreatedAt`, `fileModifiedAt`, plus `x-immich-checksum` (sha1). `200` means the checksum was already stored. |
| Album | `PUT /api/albums/{id}/assets` with `{"ids": [assetId]}` |
| Metadata | `PUT /api/assets/{id}` with description, favorite, date, GPS, rating, visibility |

`PUT /api/assets/{id}` is marked deprecated in that spec, and it is also the only asset-update operation the spec defines, so this project uses it. `deviceId` and `deviceAssetId` were removed in v3 and are not sent. `fileCreatedAt`, `fileModifiedAt`, and `dateTimeOriginal` are UTC instants. EXIF `DateTimeOriginal` keeps the wall clock from the review form, with `OffsetTimeOriginal` set from the same value.

## Tests

```bash
ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm test -- --watch=false && npm run build
```

GitHub Actions runs those checks and builds the compose file, including the mock Immich profile. The tests include synthetic beds (white lid, black lid, a print with no interior contrast), the fake scanner, and a contract test against the in-process mock.

## What this environment did not prove

A real LiDE 700F and a real Immich server were not attached here. Low-contrast prints with no edge against the lid will not be detected; draw a region for those. Prints that touch each other are found as one region; leave a few millimetres between them. The worker is a single thread, and only one scan runs at a time.
