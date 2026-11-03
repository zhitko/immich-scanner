FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends sane-utils libsane1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

ENV DATA_DIR=/data \
    SCANNER_BACKEND=sane \
    PORT=8080

VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "-m", "app"]
