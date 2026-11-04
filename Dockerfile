FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
        libgl1 \
        sane-utils \
        libsane1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-cache-dir .

COPY --from=ui /ui/dist/immich-scanner-ui /app/static

ENV DATA_DIR=/data \
    STATIC_DIR=/app/static \
    SCANNER_BACKEND=sane

VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "app"]
