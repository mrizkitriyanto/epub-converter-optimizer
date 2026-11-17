import random
from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from eco.epub.images import transform_image
from eco.options import Options, image_profile

X4 = image_profile(Options(device="x4"))
GENERAL = image_profile(Options(device="general"))


def _encode(im, fmt, **kw):
    b = BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


def _jpeg(w, h, progressive=True):
    return _encode(Image.new("RGB", (w, h), (200, 30, 30)), "JPEG", progressive=progressive)


def _noise(w, h, mode="RGB"):
    rng = random.Random(1)
    n = len(mode)
    return Image.frombytes(mode, (w, h), bytes(rng.randrange(256) for _ in range(w * h * n)))


def _line_art(w=200, h=100):
    im = Image.new("RGB", (w, h), "white")
    for x in range(0, w, 10):
        im.paste((0, 0, 0), (x, 0, x + 2, h))
    return im


def _open(out):
    return Image.open(BytesIO(out.data))


def test_photo_becomes_baseline_gray_within_screen():
    out = transform_image(_jpeg(1650, 835), image_profile(Options(device="x4")))
    im = Image.open(BytesIO(out.data))
    assert im.mode == "L" and im.width <= 480 and im.height <= 800
    assert out.media_type in ("image/jpeg", "image/png") and not im.info.get("progressive")


def test_tiny_image_removed():
    assert transform_image(_jpeg(19, 400), image_profile(Options(device="x4"))) is None


def test_xteink_line_art_becomes_gray_png():
    out = transform_image(_encode(_line_art(), "PNG"), X4)
    assert (out.ext, out.media_type) == ("png", "image/png")
    assert _open(out).format == "PNG" and _open(out).mode == "L"


def test_xteink_photo_becomes_baseline_jpeg():
    out = transform_image(_encode(_noise(300, 300), "PNG"), X4)
    im = _open(out)
    assert (out.ext, out.media_type) == ("jpg", "image/jpeg")
    assert im.format == "JPEG" and im.mode == "L" and not im.info.get("progressive")


def test_general_keeps_png_as_colour_png():
    out = transform_image(_encode(_noise(300, 300), "PNG"), GENERAL)
    im = _open(out)
    assert (out.ext, out.media_type) == ("png", "image/png")
    assert im.format == "PNG" and im.mode == "RGB"


def test_general_line_art_jpeg_source_stays_jpeg():
    out = transform_image(_encode(_line_art(), "JPEG"), GENERAL)
    assert (out.ext, _open(out).format) == ("jpg", "JPEG")


def test_general_converts_webp_to_jpeg():
    out = transform_image(_encode(_noise(100, 100), "WEBP"), GENERAL)
    assert (out.ext, out.media_type) == ("jpg", "image/jpeg")


def test_general_keeps_tiny_image():
    out = transform_image(_encode(_noise(10, 10), "PNG"), GENERAL)
    assert _open(out).size == (10, 10)


def test_general_resizes_to_profile_max():
    out = transform_image(_jpeg(3200, 1600), GENERAL)
    assert _open(out).size == (1600, 800)


def test_rgba_is_flattened_to_white():
    out = transform_image(_encode(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), "PNG"), X4)
    assert _open(out).convert("L").getpixel((25, 25)) == 255


def test_general_png_keeps_transparency():
    im = Image.new("RGBA", (50, 50), (10, 20, 30, 255))
    im.putpixel((5, 5), (0, 0, 0, 0))
    out = transform_image(_encode(im, "PNG"), GENERAL)
    result = _open(out)
    assert (out.ext, result.mode) == ("png", "RGBA")
    assert result.getpixel((5, 5))[3] == 0 and result.getpixel((25, 25)) == (10, 20, 30, 255)


def test_general_webp_alpha_becomes_jpeg_on_white():
    webp = _encode(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), "WEBP", lossless=True)
    out = transform_image(webp, GENERAL)
    assert out.ext == "jpg" and _open(out).getpixel((25, 25)) == (255, 255, 255)


def test_palette_transparency_is_flattened_to_white():
    im = Image.new("P", (50, 50), 0)
    im.putpalette([0, 0, 0] * 256)
    out = transform_image(_encode(im, "PNG", transparency=0), X4)
    assert _open(out).convert("L").getpixel((25, 25)) == 255


def test_animated_gif_uses_first_frame():
    first = Image.new("RGB", (40, 40), (0, 0, 0))
    second = Image.new("RGB", (40, 40), (255, 255, 255))
    gif = _encode(first, "GIF", save_all=True, append_images=[second], duration=100)
    out = transform_image(gif, GENERAL)
    assert out.ext == "png" and _open(out).convert("L").getpixel((20, 20)) == 0


def test_exif_orientation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 270 to display upright: a 100x50 file shows as 50x100
    out = transform_image(_encode(_noise(100, 50), "JPEG", exif=exif), GENERAL)
    assert _open(out).size == (50, 100)


def test_cmyk_jpeg_becomes_rgb():
    cmyk = Image.new("CMYK", (60, 60), (0, 255, 255, 0))
    out = transform_image(_encode(cmyk, "JPEG"), GENERAL)
    im = _open(out)
    assert im.mode == "RGB"
    r, g, b = im.getpixel((30, 30))
    assert r > 200 and g < 80 and b < 80


def test_sixteen_bit_gray_is_scaled_not_clipped():
    out = transform_image(_encode(Image.new("I;16", (50, 50), 32768), "PNG"), GENERAL)
    assert abs(_open(out).convert("L").getpixel((25, 25)) - 128) <= 2


def test_drop_images_returns_none():
    profile = image_profile(Options(device="x4", size="small", firmware="stock"))
    assert profile.drop_images and transform_image(_jpeg(100, 100), profile) is None


def test_small_image_is_never_upscaled():
    out = transform_image(_jpeg(100, 60), X4)
    assert _open(out).size == (100, 60)


def test_general_gray_png_stays_gray_and_not_larger():
    data = _encode(_noise(300, 300, "L"), "PNG", optimize=True)
    out = transform_image(data, GENERAL)
    assert _open(out).mode == "L" and len(out.data) <= len(data)


def test_general_gray_alpha_png_stays_la():
    data = _encode(Image.new("LA", (50, 50), (100, 128)), "PNG")
    assert _open(transform_image(data, GENERAL)).mode == "LA"


def test_general_gray_source_becomes_gray_jpeg():
    out = transform_image(_encode(_noise(100, 100, "L"), "TIFF"), GENERAL)
    assert (out.ext, _open(out).mode) == ("jpg", "L")


def test_general_palette_png_is_not_larger():
    data = _encode(_noise(300, 300).quantize(64), "PNG", optimize=True)
    out = transform_image(data, GENERAL)
    assert len(out.data) <= len(data)


def test_baseline_jpeg_saved_below_profile_quality_is_returned_unchanged():
    data = _encode(_noise(300, 300), "JPEG", quality=30)
    out = transform_image(data, GENERAL)
    assert out.data == data and (out.ext, out.media_type) == ("jpg", "image/jpeg")


def test_progressive_jpeg_is_reencoded_to_baseline_even_if_larger():
    data = _encode(_noise(300, 300), "JPEG", quality=30, progressive=True)
    out = transform_image(data, GENERAL)
    assert len(out.data) > len(data) and not _open(out).info.get("progressive")


def test_resized_image_is_never_returned_unchanged():
    data = _encode(_noise(900, 900), "JPEG", quality=30)
    assert _open(transform_image(data, X4)).size == (480, 480)


def test_truncated_jpeg_raises_oserror():
    data = _encode(_noise(300, 300), "JPEG")
    with pytest.raises(OSError):
        transform_image(data[: len(data) // 2], GENERAL)


def test_unreadable_data_raises():
    with pytest.raises(UnidentifiedImageError):
        transform_image(b"not an image", X4)
