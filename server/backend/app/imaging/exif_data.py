from datetime import UTC, datetime

import piexif

_OFFSET_TIME_ORIGINAL = getattr(piexif.ExifIFD, "OffsetTimeOriginal", 36881)
_OFFSET_TIME = getattr(piexif.ExifIFD, "OffsetTime", 36880)


def build_exif(
    *,
    taken_at: datetime | None,
    latitude: float | None,
    longitude: float | None,
    description: str,
) -> bytes:
    zeroth: dict[int, object] = {piexif.ImageIFD.Software: "immich-scanner"}
    exif: dict[int, object] = {}
    gps: dict[int, object] = {}
    if description:
        zeroth[piexif.ImageIFD.ImageDescription] = description[:5000]
    if taken_at is not None:
        wall = taken_at.strftime("%Y:%m:%d %H:%M:%S")
        zeroth[piexif.ImageIFD.DateTime] = wall
        exif[piexif.ExifIFD.DateTimeOriginal] = wall
        exif[piexif.ExifIFD.DateTimeDigitized] = wall
        offset = _offset_label(taken_at)
        exif[_OFFSET_TIME] = offset
        exif[_OFFSET_TIME_ORIGINAL] = offset
    if latitude is not None and longitude is not None:
        gps[piexif.GPSIFD.GPSLatitudeRef] = "N" if latitude >= 0 else "S"
        gps[piexif.GPSIFD.GPSLatitude] = _dms(abs(latitude))
        gps[piexif.GPSIFD.GPSLongitudeRef] = "E" if longitude >= 0 else "W"
        gps[piexif.GPSIFD.GPSLongitude] = _dms(abs(longitude))
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps})


def format_immich_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _offset_label(value: datetime) -> str:
    raw = value.strftime("%z") or "+0000"
    return f"{raw[:3]}:{raw[3:]}"


def _dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    if seconds >= 59.9995:
        seconds = 0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        degrees += 1
    return ((degrees, 1), (minutes, 1), (int(round(seconds * 10000)), 10000))
