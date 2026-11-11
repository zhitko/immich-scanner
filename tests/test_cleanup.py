import sqlite3

import cv2
import numpy as np
from alembic.config import Config

from alembic import command
from app.retouch.cleanup import deblur, gentle_denoise, remove_dust
from app.retouch.engine import OnnxRetoucher
from app.retouch.options import RetouchOptions, option_token, options_from_token
from tests.synthetic import encode_png, make_bed
from tests.test_api import _import_bed


def test_dust_repairs_specks_but_keeps_long_edges():
    image = np.full((100, 100, 3), 120, np.uint8)
    image[25:27, 25:27] = 255
    image[70, 70] = 0
    image[10:90, 50:53] = 240
    result = remove_dust(image)
    assert np.max(np.abs(result[25:27, 25:27].astype(int) - 120)) < 5
    assert np.max(np.abs(result[70, 70].astype(int) - 120)) < 5
    np.testing.assert_array_equal(result[10:90, 50:53], image[10:90, 50:53])


def test_gentle_denoise_reduces_noise_without_resizing():
    rng = np.random.default_rng(12)
    image = np.clip(128 + rng.normal(0, 3, (80, 90, 3)), 0, 255).astype(np.uint8)
    result = gentle_denoise(image)
    assert result.shape == image.shape
    assert result.std() < image.std() * 0.8
    assert abs(result.mean() - image.mean()) < 2


def test_deblur_improves_mild_defocus_and_preserves_flat_field():
    sharp = np.full((300, 100, 3), 60, np.uint8)
    sharp[:, 50:] = 190
    blurred = cv2.GaussianBlur(sharp, (7, 7), 0.8)
    result = deblur(blurred)
    assert np.mean((result.astype(float) - sharp) ** 2) < np.mean(
        (blurred.astype(float) - sharp) ** 2
    )
    assert result.min() >= 55 and result.max() <= 195
    np.testing.assert_allclose(result[255], result[256], atol=1)
    flat = np.full((80, 90, 3), 128, np.uint8)
    np.testing.assert_allclose(deblur(flat), flat, atol=1)


def test_cleanup_needs_no_weights_and_reports_stages(tmp_path):
    options = RetouchOptions(dust=True, gentle_denoise=True, deblur=True)
    stages, progress = [], []
    image = np.full((64, 64, 3), 128, np.uint8)
    result = OnnxRetoucher(tmp_path).apply(image, options, progress.append, stages.append)
    assert result.shape == image.shape
    assert len(stages) == 3
    assert progress[-1] == 99
    assert options_from_token(option_token(options)) == options


def test_two_times_output_before_faces(tmp_path, monkeypatch):
    engine = OnnxRetoucher(tmp_path)
    monkeypatch.setattr(engine, "_require", lambda options: None)
    monkeypatch.setattr(engine, "_restore", lambda image, *args, **kwargs: np.repeat(
        np.repeat(image, 4, axis=0), 4, axis=1
    ))
    seen = []

    def faces(image, **kwargs):
        seen.append(image.shape)
        return image

    monkeypatch.setattr(engine, "_faces", faces)
    image = np.full((30, 40, 3), 128, np.uint8)
    options = RetouchOptions(upscale=True, output_scale=2, faces=True)
    result = engine.apply(image, options)
    assert result.shape == (60, 80, 3)
    assert seen == [result.shape]
    assert options_from_token(option_token(options)) == options


def test_cleanup_settings_jobs_and_stale_output(client, app_bundle):
    app, services = app_bundle
    saved = client.put('/api/settings', json={
        'retouch_dust': True, 'retouch_deblur': True,
        'retouch_gentle_denoise': True, 'retouch_output_scale': 2,
        'retouch_paper_mesh': True, 'retouch_paper_embossed': True,
    })
    assert saved.status_code == 200
    scan_id = _import_bed(services, encode_png(make_bed()))
    app.state.worker.process_available()
    region = client.get(f'/api/scans/{scan_id}').json()['regions'][0]
    assert region['retouch_dust'] and region['retouch_deblur']
    assert region['retouch_gentle_denoise'] and region['retouch_output_scale'] == 2
    assert region['retouch_paper_mesh'] and region['retouch_paper_embossed']
    url = f'/api/scans/{scan_id}/regions/{region["id"]}'
    assert client.post(url + '/retouch', json={'paper_mesh': True}).status_code == 202
    app.state.worker.process_available()
    ready = client.get(f'/api/scans/{scan_id}').json()['regions'][0]
    assert ready['retouch_ready']
    changed = client.patch(url, json={'retouch_paper_embossed': True})
    assert changed.json()['retouch_status'] == 'stale'
    assert client.post(url + '/retouch', json={'dust': True, 'output_scale': 3}).status_code == 422


def test_cleanup_migration_defaults_and_downgrade(tmp_path):
    database = tmp_path / 'migration.sqlite'
    config = Config('alembic.ini')
    config.set_main_option('sqlalchemy.url', f'sqlite:///{database}')
    command.upgrade(config, '0004_photo_levels')
    command.upgrade(config, 'head')
    with sqlite3.connect(database) as connection:
        columns = {row[1]: row for row in connection.execute('PRAGMA table_info(regions)')}
        for name in ('retouch_dust', 'retouch_deblur', 'retouch_gentle_denoise',
                     'retouch_paper_mesh', 'retouch_paper_embossed'):
            assert columns[name][3] == 1
            assert columns[name][4] == '0'
        assert columns['retouch_output_scale'][4] == "'4'"
    command.downgrade(config, '0004_photo_levels')
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(regions)')}
        assert 'retouch_dust' not in columns
        assert 'retouch_contrast' in columns
