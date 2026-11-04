import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app_bundle(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'archive.db'}",
        static_dir=tmp_path / "no-ui",
        scanner_backend="fake",
        worker_enabled=False,
    )
    app = create_app(settings)
    try:
        yield app, app.state.services
    finally:
        app.state.services.engine.dispose()


@pytest.fixture
def client(app_bundle):
    app, _services = app_bundle
    with TestClient(app) as test_client:
        yield test_client
