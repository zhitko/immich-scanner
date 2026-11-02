FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY server/frontend/package.json server/frontend/package-lock.json ./
RUN npm ci
COPY server/frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/backend/pyproject.toml server/backend/alembic.ini ./
COPY server/backend/alembic ./alembic
COPY server/backend/app ./app
RUN pip install --no-cache-dir .

COPY --from=ui /ui/dist/immich-scanner-ui /app/static

ENV DATA_DIR=/data \
    STATIC_DIR=/app/static \
    SCANNER_API_TOKEN=change-me

VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "app"]
