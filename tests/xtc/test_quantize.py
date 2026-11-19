from io import BytesIO

import numpy as np
from PIL import Image

from eco.style import PageStyle
from eco.xtc.quantize import _fs, quantize_page


def png(values: list[list[int]]) -> bytes:
    image = Image.fromarray(np.array(values, dtype=np.uint8), mode="L")
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def pixels(image: Image.Image) -> np.ndarray:
    return np.asarray(image)


def reference_fs(region: np.ndarray, levels: np.ndarray, strength: float) -> np.ndarray:
    a = region.astype(np.float32)
    height, width = a.shape
    for y in range(height):
        for x in range(width):
            old = a[y, x]
            new = levels[np.abs(levels - old).argmin()]
            a[y, x] = new
            error = (old - new) * strength
            if x + 1 < width:
                a[y, x + 1] += error * 7 / 16
            if y + 1 < height:
                if x > 0:
                    a[y + 1, x - 1] += error * 3 / 16
                a[y + 1, x] += error * 5 / 16
                if x + 1 < width:
                    a[y + 1, x + 1] += error / 16
    return a.clip(0, 255).astype(np.uint8)


def test_xth_uses_only_four_levels():
    image = quantize_page(png([[0, 42, 43, 127, 128, 212, 213, 255]]), [], PageStyle())

    assert set(pixels(image).flat) <= {0, 85, 170, 255}
    assert pixels(image).tolist() == [[0, 0, 85, 85, 170, 170, 255, 255]]


def test_page_without_boxes_does_not_dither():
    source = png([[64, 128, 192]])

    weak = quantize_page(source, [], PageStyle(dither_strength=0))
    strong = quantize_page(source, [], PageStyle(dither_strength=100))

    assert weak.tobytes() == strong.tobytes()


def test_flat_image_box_is_dithered_only_when_enabled():
    source = png([[128] * 8 for _ in range(8)])
    box = [(0, 0, 8, 8)]

    dithered = quantize_page(source, box, PageStyle(dither=True, dither_strength=100))
    crisp = quantize_page(source, box, PageStyle(dither=False))

    assert set(pixels(dithered).flat) == {85, 170}
    assert set(pixels(crisp).flat) == {170}


def test_non_square_box_uses_left_top_right_bottom_coordinates():
    source = png([[128] * 5 for _ in range(4)])

    image = quantize_page(source, [(1, 0, 3, 4)], PageStyle(dither_strength=100))
    changed = pixels(image) == 85

    assert changed[:, 0].sum() == 0
    assert changed[:, 3:].sum() == 0
    assert changed[:, 1:3].sum() > 0


def test_box_at_and_past_page_edge_is_clipped():
    source = png([[128] * 4 for _ in range(3)])

    image = quantize_page(source, [(2, 1, 9, 8)], PageStyle(dither_strength=100))
    changed = pixels(image) == 85

    assert changed[:1].sum() == 0
    assert changed[:, :2].sum() == 0
    assert changed[1:, 2:].sum() > 0


def test_negative_is_applied_after_quantization():
    image = quantize_page(png([[255]]), [], PageStyle(negative=True))

    assert image.getpixel((0, 0)) == 0


def test_xtg_uses_only_black_and_white():
    image = quantize_page(
        png([[0, 127, 128, 255]]),
        [(0, 0, 4, 1)],
        PageStyle(mode="xtg", dither=False),
    )

    assert set(pixels(image).flat) == {0, 255}
    assert pixels(image).tolist() == [[0, 0, 255, 255]]


def test_fs_list_loop_matches_numpy_reference():
    rng = np.random.default_rng(20261119)
    levels = np.array([0, 85, 170, 255], dtype=np.float32)
    regions = [
        rng.integers(0, 256, size=(73, 101), dtype=np.uint8),
        np.full((9, 13), 128, dtype=np.uint8),
    ]

    for region in regions:
        assert np.array_equal(_fs(region, levels, 0.8), reference_fs(region, levels, 0.8))


def test_full_x4_page_png_round_trip():
    source = Image.new("L", (480, 800), 128)
    raw = BytesIO()
    source.save(raw, "PNG")

    image = quantize_page(raw.getvalue(), [], PageStyle())

    assert image.mode == "L"
    assert image.size == (480, 800)
    assert set(pixels(image).flat) == {170}
