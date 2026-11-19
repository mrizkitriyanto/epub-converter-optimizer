"""Encode and decode Xteink XTG and XTH pages."""

import struct

import numpy as np
from PIL import Image

_HEADER = struct.Struct("<4sHHBBI8s")

# verify with devcheck on device
XTH_VALUES = {255: 0, 170: 2, 85: 1, 0: 3}
_XTH_PIXELS = np.array([255, 85, 170, 0], dtype=np.uint8)


def _image(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"))


def _header(magic: bytes, width: int, height: int, data_size: int) -> bytes:
    return _HEADER.pack(magic, width, height, 0, 0, data_size, bytes(8))


def encode_xtg(image: Image.Image) -> bytes:
    """Encode a black-and-white image in row-major XTG layout."""
    pixels = _image(image)
    payload = np.packbits(pixels == 255, axis=1, bitorder="big").tobytes()
    return _header(b"XTG\0", image.width, image.height, len(payload)) + payload


def encode_xth(image: Image.Image) -> bytes:
    """Encode a four-level image in CrossPoint's two-plane XTH layout."""
    pixels = _image(image)
    if not set(np.unique(pixels)) <= XTH_VALUES.keys():
        raise ValueError("XTH pixels must be 0, 85, 170 or 255")
    lookup = np.full(256, 255, dtype=np.uint8)
    for pixel, code in XTH_VALUES.items():
        lookup[pixel] = code
    codes = lookup[pixels]
    high = np.packbits(((codes >> 1) & 1)[:, ::-1].T, axis=1, bitorder="big")
    low = np.packbits((codes & 1)[:, ::-1].T, axis=1, bitorder="big")
    payload = high.tobytes() + low.tobytes()
    return _header(b"XTH\0", image.width, image.height, len(payload)) + payload


def decode_page(data: bytes) -> Image.Image:
    """Decode one XTG or XTH page."""
    if len(data) < _HEADER.size:
        raise ValueError("Page data is shorter than its header")
    magic, width, height, reserved_a, reserved_b, data_size, _ = _HEADER.unpack_from(data)
    payload = data[_HEADER.size :]
    if reserved_a or reserved_b or len(payload) != data_size:
        raise ValueError("Invalid page header")

    if magic == b"XTG\0":
        row_size = (width + 7) // 8
        if data_size != row_size * height:
            raise ValueError("Invalid XTG data size")
        packed = np.frombuffer(payload, dtype=np.uint8).reshape(height, row_size)
        pixels = np.unpackbits(packed, axis=1, bitorder="big")[:, :width] * 255
    elif magic == b"XTH\0":
        column_size = (height + 7) // 8
        plane_size = width * column_size
        if data_size != plane_size * 2:
            raise ValueError("Invalid XTH data size")
        planes = []
        for start in (0, plane_size):
            packed = np.frombuffer(payload[start : start + plane_size], dtype=np.uint8).reshape(
                width, column_size
            )
            planes.append(np.unpackbits(packed, axis=1, bitorder="big")[:, :height].T[:, ::-1])
        pixels = _XTH_PIXELS[(planes[0] << 1) | planes[1]]
    else:
        raise ValueError("Unknown page format")
    return Image.fromarray(pixels.astype(np.uint8))
