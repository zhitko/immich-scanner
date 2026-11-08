from datetime import UTC, datetime
from io import BytesIO

import numpy as np
import piexif
import pytest
from PIL import Image

from app.imaging.exif_data import build_exif, format_immich_datetime
from app.imaging.io import save_rgb


def test_exif_records_wall_time_offset_and_gps(tmp_path) -> None:
    taken = datetime(1998, 6, 2, 15, 4, 5, tzinfo=UTC)
    payload = build_exif(
        taken_at=taken,
        latitude=48.2,
        longitude=-16.5,
        description="Beach",
    )
    image = np.zeros((8, 8, 3), np.uint8)
    path = tmp_path / "photo.jpg"
    save_rgb(image, path, "jpeg", exif=payload, dpi=300)
    loaded = piexif.load(path.read_bytes())
    assert loaded["0th"][piexif.ImageIFD.Software] == b"immich-scanner"
    assert loaded["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"1998:06:02 15:04:05"
    assert loaded["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"
    assert loaded["GPS"][piexif.GPSIFD.GPSLongitudeRef] == b"W"
    with Image.open(BytesIO(path.read_bytes())) as picture:
        assert int(round(picture.info["dpi"][0])) == 300
    assert format_immich_datetime(taken) == "1998-06-02T15:04:05.000Z"


@pytest.mark.parametrize("output_format", ["jpeg", "png"])
@pytest.mark.parametrize(
    "description",
    ["Beach", "Café", "Příliš žluťoučký kůň", "家族写真 📷", "📷" * 5001],
    ids=["ascii", "latin1", "czech", "cjk-emoji", "truncated-emoji"],
)
def test_exif_description_round_trips_unicode(tmp_path, output_format, description) -> None:
    payload = build_exif(taken_at=None, latitude=None, longitude=None, description=description)
    path = tmp_path / f"photo.{output_format}"
    save_rgb(np.zeros((8, 8, 3), np.uint8), path, output_format, exif=payload, dpi=300)
    with Image.open(path) as picture:
        loaded = piexif.load(picture.info["exif"])
    assert loaded["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == description[:5000]
