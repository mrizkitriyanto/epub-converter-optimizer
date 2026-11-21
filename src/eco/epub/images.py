from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps

from eco.options import ImageProfile

_LINE_ART_COLORS = 16
_QUALITY_STEP = 2  # an enhanced photo bigger than a plain one is encoded again, this much lower,
_MAX_QUALITY_DROP = 15  # down to at most this far below the profile's quality


def _jpeg(im: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    im.save(out, "JPEG", progressive=False, optimize=True, quality=quality)
    return out.getvalue()


def _enhanced_jpeg(im: Image.Image, quality: int) -> bytes:
    """A flat, muddy photo on e-ink: its levels stretched and a little sharpening, never bigger
    than the photo without them. The quality steps down to make room; when even the lowest one is
    too big, the photo keeps only the stretched levels, and failing that it stays as it was."""
    plain = _jpeg(im, quality)
    contrast = ImageOps.autocontrast(im, cutoff=1)
    sharp = contrast.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=2))
    for candidate in (sharp, contrast):
        for lower in range(quality, quality - _MAX_QUALITY_DROP - 1, -_QUALITY_STEP):
            encoded = _jpeg(candidate, lower)
            if len(encoded) <= len(plain):
                return encoded
    return plain


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
    elif profile.enhance:
        result = ImageResult(_enhanced_jpeg(im, profile.jpeg_quality), "image/jpeg", "jpg")
    else:
        result = ImageResult(_jpeg(im, profile.jpeg_quality), "image/jpeg", "jpg")
    # an enhanced photo is never swapped back for its source
    enhanced = profile.enhance and not png
    if final_form and not enhanced and im.size == size and len(data) <= len(result.data):
        media_type, ext = ("image/png", "png") if source_format == "PNG" else ("image/jpeg", "jpg")
        return ImageResult(data, media_type, ext)
    return result
