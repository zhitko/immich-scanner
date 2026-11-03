# immich-scanner

Scan several physical photos at once on a flatbed, separate them, review the crops in a browser, and upload each photo to a self-hosted [Immich](https://immich.app) album.

The laptop that owns the scanner runs a small agent. A home server stores the scans, detects the photos, and serves the review UI. The two machines only share an HTTP API.

```
laptop (USB scanner)                home server
client/  FastAPI + scanimage   →    server/  FastAPI + Angular
         full-bed TIFF/PNG           detect, review, crop, upload
```

## Run with Docker

Each compose file starts one side.

```bash
cp server/.env.example server/.env
docker compose -f docker-compose.server.yml up --build
```

The review UI and API are then at `http://<home-server>:8080`. The original scans, crops, and SQLite database stay in the `server-data` volume.

On the laptop:

```bash
cp client/.env.example client/.env
# set SERVER_URL to http://<home-server>:8080 and the same SCANNER_API_TOKEN
docker compose -f docker-compose.client.yml up --build
```

The agent UI is at `http://<laptop>:8081`. Open it, confirm the scanner and the server are both reachable, and press Scan. The agent captures the whole bed and uploads it. The server queues detection on its own.

### Without a scanner or a real Immich

```bash
# server .env
SCANNER_API_TOKEN=change-me
IMMICH_BASE_URL=http://mock-immich:3001
IMMICH_API_KEY=dev-key

docker compose -f docker-compose.server.yml --profile mock up --build
```

The mock speaks the small part of the Immich API this project uses (version, albums, asset upload, metadata update, album membership). It forgets everything when the container stops.

For the agent, set `SCANNER_BACKEND=fake` in `client/.env` before the first start. The fake scanner returns the same three-print bed every time, so detection and review can be exercised with no USB device. If a settings file already exists in the volume, change the backend from the agent's settings page instead. The page wins over the environment after the first save.

## USB scanner

The expected device is a Canon CanoScan LiDE 700F (`04a9:1907`), driven by SANE's genesys backend through `scanimage`. The client image installs `sane-utils` and `libsane1`. The compose file starts the container privileged and bind-mounts `/dev/bus/usb`, and the process runs as root so it can open the device node.

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

The default scan is the full bed: `scanimage` is called without `-x` or `-y`, so the backend's own scan area is used (about 216×297 mm on this model). Resolution defaults to 300 dpi and the file is a lossless TIFF. PNG and a smaller window, in millimetres, are available in the agent settings. The source is left at the backend default, which is the flatbed rather than the transparency unit.

## Run from a checkout

Python 3.12 and Node 22.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e "./server/backend[dev]" -e "./client[dev]"

# review API
cd server/backend
SCANNER_API_TOKEN=change-me DATA_DIR=./data python -m app

# mock Immich, optional, on port 3001
python -m mock_immich

# review UI during development (proxies /api to port 8000)
cd server/frontend && npm ci && npm start

# agent with the fake scanner, UI on port 8080
cd client
SCANNER_BACKEND=fake SERVER_URL=http://127.0.0.1:8000 API_TOKEN=change-me python -m app
```

To serve the built UI from the API instead of `ng serve`, run `npm run build` in `server/frontend` and start the API with `STATIC_DIR` pointed at `server/frontend/dist/immich-scanner-ui`.

## Review UI

The desk is one Angular app:

- **Waiting** lists scans that are not fully uploaded. Open one to see the bed with the detected regions drawn on top.
- Drag a region to move it, drag a corner to resize it, and drag the handle above the selection to rotate it. Add a region, delete one, or run detection again. Detection replaces only regions that have not been uploaded.
- Each photo has a date taken, description, album, location, favorite flag, rating, and visibility. The date is written into EXIF and sent to Immich. Rotate by 90° clockwise when a print is sideways. The crop preview is the straightened photo.
- **Upload** writes a full-resolution JPEG (quality from settings, default 95, 4:4:4) or a PNG, then creates the Immich asset, adds it to the album, and updates the metadata. A failed photo can be retried. If the crop changed after a successful upload, the next upload creates a new asset and leaves the previous one in Immich.
- **Uploaded** keeps the history, including Immich asset ids, and can delete the original scan file to free disk space.
- **Jobs** shows queued, running, finished, and failed detection and upload work.
- **Settings** stores the Immich URL and API key, tests the connection, and lists albums.

The review API is not authenticated. Only `POST /api/ingest/scans` requires `X-Scanner-Token`, and an empty token is rejected. Keep the server on the home network.

The Immich API key needs `asset.upload`, `asset.update`, `album.read`, and `albumAsset.create`.

## How detection and uploads run

Jobs live in the same SQLite database as the scans (`jobs` table, WAL). One worker thread in the API process claims the oldest queued job. A job left in `running` after a crash is queued again on startup. Redis or Celery would only add another service for a single home server that already persists everything in SQLite.

Detection downscales the bed, flood-fills whichever lid color is on the border, and turns the remaining contours into minimum-area rectangles. Specks are ignored. The close kernel stays smaller than a 5 mm gap so neighbouring prints are not merged. The detector is the `PhotoDetector` protocol; `OpenCvPhotoDetector` is the implementation used by the app.

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
cd client && ruff check . && ruff format --check . && pytest
cd server/backend && ruff check . && ruff format --check . && pytest
cd server/frontend && npm run lint && npm test -- --watch=false && npm run build
```

GitHub Actions runs those checks and builds both compose files. The server tests include synthetic beds (white lid, black lid, a print with no interior contrast) and a contract test against the in-process mock.

## What this environment did not prove

A real LiDE 700F and a real Immich server were not attached here. Low-contrast prints with no edge against the lid will not be detected; draw a region for those. Running detection again can leave an uploaded region overlapping a newly found one. The worker is a single thread.
