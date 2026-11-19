from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from eco.options import ImageProfile

_LINE_ART_COLORS = 16
_WIDE_INT_MODES = ("I", "I;16", "I;16L", "I;16B", "I;16N")
_ORIENTATION = 0x0112


@dataclass
class ImageResult:
    data: bytes
    media_type: str
    ext: str


def _normalise(im: Image.Image, profile: ImageProfile, keep_alpha: bool) -> Image.Image:
    if im.mode in _WIDE_INT_MODES:
        im = im.point(lambda v: v * (1 / 256))  # assumes 16-bit range, plain convert clips to white
    gray = profile.grayscale or im.mode in ("1", "L", "LA") or im.mode in _WIDE_INT_MODES
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        if keep_alpha:
            return rgba.convert("LA") if gray else rgba
        im = Image.new("RGBA", rgba.size, "white")
        im.alpha_composite(rgba)
    return im.convert("L" if gray else "RGB")


def _is_line_art(im: Image.Image) -> bool:
    # NEAREST keeps exact colours, so anti-aliasing does not inflate the count
    small = im.resize((64, 64), Image.Resampling.NEAREST)
    return small.getcolors(maxcolors=_LINE_ART_COLORS) is not None


def _is_final_form(src: Image.Image, profile: ImageProfile) -> bool:
    """True when the source could be returned as is (if no resize happens and it is smaller)."""
    if src.getexif().get(_ORIENTATION, 1) != 1 or getattr(src, "is_animated", False):
        return False
    if src.format == "JPEG":
        ok = not src.info.get("progressive") and src.mode in ("L", "RGB")
    else:
        ok = src.format == "PNG"
    if profile.grayscale:
        ok = ok and src.mode in ("L", "1") and "transparency" not in src.info
    return ok


def transform_image(data: bytes, profile: ImageProfile) -> ImageResult | None:
    """Re-encode an image for the profile, or return None to remove it.

    Raises OSError for undecodable, truncated or corrupt input
    (PIL.UnidentifiedImageError is a subclass).
    """
    if profile.drop_images:
        return None
    with Image.open(BytesIO(data)) as src:
        source_format = src.format
        final_form = _is_final_form(src, profile)
        im = ImageOps.exif_transpose(src)  # first frame for animated sources
        if min(im.size) < profile.min_px:
            return None
        size = im.size
        png = not profile.png_line_art and source_format in ("PNG", "GIF")
        im = _normalise(im, profile, keep_alpha=png)
    im.thumbnail((profile.max_w, profile.max_h))
    if profile.png_line_art:
        png = _is_line_art(im)
    out = BytesIO()
    if png:
        im.save(out, "PNG", optimize=True)
        result = ImageResult(out.getvalue(), "image/png", "png")
    else:
        im.save(out, "JPEG", progressive=False, optimize=True, quality=profile.jpeg_quality)
        result = ImageResult(out.getvalue(), "image/jpeg", "jpg")
    if final_form and im.size == size and len(data) <= len(result.data):
        media_type, ext = ("image/png", "png") if source_format == "PNG" else ("image/jpeg", "jpg")
        return ImageResult(data, media_type, ext)
    return result
