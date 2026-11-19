import struct

import numpy as np
import pytest
from PIL import Image

from eco.xtc.codec import decode_page, encode_xtg, encode_xth


def test_xtg_header_and_bits():
    image = Image.new("L", (10, 2), 255)
    image.putpixel((0, 0), 0)

    data = encode_xtg(image)

    assert data[:4] == b"XTG\0"
    assert struct.unpack("<HHBBI", data[4:14]) == (10, 2, 0, 0, 4)
    assert data[22] == 0x7F


def test_xth_known_vector():
    image = Image.new("L", (8, 8), 255)
    image.putpixel((7, 0), 0)

    data = encode_xth(image)

    plane_size = 8
    assert data[22] == 0x80
    assert data[22 + plane_size] == 0x80
    assert not any(data[23 : 22 + plane_size])
    assert not any(data[23 + plane_size :])


@pytest.mark.parametrize("size", [(480, 800), (528, 792)])
def test_xth_round_trip(size):
    values = np.random.default_rng(1).choice([0, 85, 170, 255], size=size[::-1]).astype(np.uint8)
    image = Image.fromarray(values)

    decoded = decode_page(encode_xth(image))

    assert decoded.mode == "L"
    assert decoded.size == size
    assert np.array_equal(np.asarray(decoded), values)


def test_xtg_round_trip_with_partial_byte():
    values = np.random.default_rng(2).choice([0, 255], size=(7, 13)).astype(np.uint8)
    image = Image.fromarray(values)

    decoded = decode_page(encode_xtg(image))

    assert np.array_equal(np.asarray(decoded), values)
