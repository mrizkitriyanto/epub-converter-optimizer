from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from eco.options import ImageProfile

_LINE_ART_COLORS = 16
_WIDE_INT_MODES = ("I", "I;16", "I;16L", "I;16B", "I;16N")


@dataclass
class ImageResult:
    data: bytes
    media_type: str
    ext: str


def _normalise(im: Image.Image, grayscale: bool, keep_alpha: bool) -> Image.Image:
    if im.mode in _WIDE_INT_MODES:
        im = im.point(lambda v: v * (1 / 256))  # assumes 16-bit range, plain convert clips to white
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        if keep_alpha:
            return im.convert("RGBA")
        rgba = im.convert("RGBA")
        im = Image.new("RGBA", rgba.size, "white")
        im.alpha_composite(rgba)
    return im.convert("L" if grayscale else "RGB")


def _is_line_art(im: Image.Image) -> bool:
    # NEAREST keeps exact colours, so anti-aliasing does not inflate the count
    small = im.resize((64, 64), Image.Resampling.NEAREST)
    return small.getcolors(maxcolors=_LINE_ART_COLORS) is not None


def transform_image(data: bytes, profile: ImageProfile) -> ImageResult | None:
    if profile.drop_images:
        return None
    with Image.open(BytesIO(data)) as src:
        source_format = src.format
        im = ImageOps.exif_transpose(src)  # first frame for animated sources
        if min(im.size) < profile.min_px:
            return None
        png = not profile.png_line_art and source_format in ("PNG", "GIF")
        im = _normalise(im, profile.grayscale, keep_alpha=png)
    im.thumbnail((profile.max_w, profile.max_h))
    if profile.png_line_art:
        png = _is_line_art(im)
    out = BytesIO()
    if png:
        im.save(out, "PNG", optimize=True)
        return ImageResult(out.getvalue(), "image/png", "png")
    im.save(out, "JPEG", progressive=False, optimize=True, quality=profile.jpeg_quality)
    return ImageResult(out.getvalue(), "image/jpeg", "jpg")
