from pathlib import Path

from PIL import Image, ImageDraw

from app.scanner.base import ScannerDevice, ScanRequest

# Fixed sample bed. Pixel size stays modest so dev machines are not asked to
# synthesize a 600 dpi A4 TIFF; the requested dpi is written into the file.
_BED_SIZE = (1200, 1700)


class FakeScanner:
    """Return a deterministic bed with three prints and one dust speck.

    The prints have a contrasting edge and a gap between them so the server
    detector can separate them the same way it would a real lid scan.
    """

    def list_devices(self) -> list[ScannerDevice]:
        return [ScannerDevice(name="fake:0", description="Fake flatbed scanner")]

    def scan(self, request: ScanRequest, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        image = render_sample_bed()
        dpi = (request.resolution_dpi, request.resolution_dpi)
        if request.image_format == "png":
            image.save(destination, format="PNG", dpi=dpi)
        else:
            image.save(destination, format="TIFF", dpi=dpi, compression="tiff_lzw")


def render_sample_bed() -> Image.Image:
    width, height = _BED_SIZE
    background = (248, 248, 246)
    image = Image.new("RGB", (width, height), background)
    photos = (
        ((176, 48, 42), (90, 80, 460, 320), -7),
        ((36, 78, 150), (640, 180, 430, 300), 0),
        ((34, 120, 78), (180, 980, 620, 420), 5),
    )
    for color, box, angle in photos:
        _paste_print(image, color, box, angle, background)
    dust = ImageDraw.Draw(image)
    dust.rectangle((width - 40, height - 36, width - 28, height - 24), fill=(20, 20, 20))
    return image


def _paste_print(
    bed: Image.Image,
    color: tuple[int, int, int],
    box: tuple[int, int, int, int],
    angle: float,
    background: tuple[int, int, int],
) -> None:
    left, top, photo_width, photo_height = box
    photo = Image.new("RGB", (photo_width, photo_height), color)
    draw = ImageDraw.Draw(photo)
    draw.rectangle((0, 0, photo_width - 1, photo_height - 1), outline=(18, 18, 18), width=8)
    draw.rectangle((36, 36, photo_width // 2, photo_height // 2), fill=_shift(color, 30))
    rotated = photo.rotate(
        angle,
        expand=True,
        resample=Image.Resampling.BICUBIC,
        fillcolor=background,
    )
    bed.paste(rotated, (left, top))


def _shift(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    red, green, blue = color
    return (
        max(0, min(255, red + amount)),
        max(0, min(255, green + amount)),
        max(0, min(255, blue + amount)),
    )
