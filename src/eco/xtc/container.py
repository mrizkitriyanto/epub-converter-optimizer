"""Write and read XTC and XTCH containers."""

import struct
import time
from dataclasses import dataclass

_HEADER = struct.Struct("<4s2sHBBBBIQQQQQ")
_INDEX = struct.Struct("<QIHH")
_CHAPTER_SIZE = 96
_METADATA_OFFSET = 56
_METADATA_SIZE = 256
_CHAPTER_OFFSET = _METADATA_OFFSET + _METADATA_SIZE


@dataclass(frozen=True)
class Chapter:
    title: str
    start: int
    end: int


def _text(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")[: size - 1]
    raw = raw.decode("utf-8", errors="ignore").encode("utf-8")
    return raw + bytes(size - len(raw))


def _read_text(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8")


def write_container(
    pages: list[bytes],
    *,
    hq: bool,
    width: int,
    height: int,
    title: str,
    author: str,
    language: str,
    chapters: list[Chapter],
    created: int | None = None,
) -> bytes:
    """Build one complete XTC or XTCH file."""
    index_offset = _CHAPTER_OFFSET + len(chapters) * _CHAPTER_SIZE
    data_offset = index_offset + len(pages) * _INDEX.size
    header = _HEADER.pack(
        b"XTCH" if hq else b"XTC\0",
        b"\x01\x00",
        len(pages),
        0,
        1,
        0,
        bool(chapters),
        1,
        _METADATA_OFFSET,
        index_offset,
        data_offset,
        0,
        _CHAPTER_OFFSET,
    )

    metadata = bytearray(_METADATA_SIZE)
    metadata[0:128] = _text(title, 128)
    metadata[128:192] = _text(author, 64)
    metadata[192:224] = _text("eco", 32)
    metadata[224:240] = _text(language, 16)
    struct.pack_into(
        "<IHH",
        metadata,
        240,
        int(time.time()) if created is None else created,
        0xFFFF,
        len(chapters),
    )

    chapter_data = bytearray()
    for chapter in chapters:
        entry = bytearray(_CHAPTER_SIZE)
        entry[:80] = _text(chapter.title, 80)
        struct.pack_into("<HH", entry, 80, chapter.start + 1, chapter.end + 1)
        chapter_data.extend(entry)

    index = bytearray()
    offset = data_offset
    for page in pages:
        index.extend(_INDEX.pack(offset, len(page), width, height))
        offset += len(page)
    return header + metadata + chapter_data + index + b"".join(pages)


def read_container(data: bytes) -> tuple[dict, list[bytes], list[Chapter]]:
    """Read the fields eco writes, validating offsets before slicing."""
    if len(data) < _CHAPTER_OFFSET:
        raise ValueError("Container is shorter than its metadata")
    (
        magic,
        version,
        page_count,
        _direction,
        has_metadata,
        _has_thumbnails,
        has_chapters,
        _current_page,
        metadata_offset,
        index_offset,
        data_offset,
        _thumbnail_offset,
        chapter_offset,
    ) = _HEADER.unpack_from(data)
    if magic not in (b"XTC\0", b"XTCH") or version != b"\x01\x00":
        raise ValueError("Unknown container format")
    if (
        not has_metadata
        or metadata_offset != _METADATA_OFFSET
        or chapter_offset != _CHAPTER_OFFSET
        or not (_CHAPTER_OFFSET <= index_offset <= data_offset <= len(data))
    ):
        raise ValueError("Invalid container offsets")

    metadata_raw = data[metadata_offset : metadata_offset + _METADATA_SIZE]
    created, marker, chapter_count = struct.unpack_from("<IHH", metadata_raw, 240)
    if marker != 0xFFFF or bool(chapter_count) != bool(has_chapters):
        raise ValueError("Invalid container metadata")

    chapters = []
    for number in range(chapter_count):
        start = chapter_offset + number * _CHAPTER_SIZE
        entry = data[start : start + _CHAPTER_SIZE]
        if len(entry) != _CHAPTER_SIZE or start + _CHAPTER_SIZE > index_offset:
            raise ValueError("Invalid chapter table")
        first, last = struct.unpack_from("<HH", entry, 80)
        chapters.append(Chapter(_read_text(entry[:80]), first - 1, last - 1))

    pages = []
    width = height = 0
    for number in range(page_count):
        entry = index_offset + number * _INDEX.size
        if entry + _INDEX.size > data_offset:
            raise ValueError("Invalid page index")
        offset, size, page_width, page_height = _INDEX.unpack_from(data, entry)
        if offset < data_offset or offset + size > len(data):
            raise ValueError("Invalid page offset")
        if number == 0:
            width, height = page_width, page_height
        elif (page_width, page_height) != (width, height):
            raise ValueError("Page dimensions do not match")
        pages.append(data[offset : offset + size])

    metadata = {
        "hq": magic == b"XTCH",
        "width": width,
        "height": height,
        "title": _read_text(metadata_raw[:128]),
        "author": _read_text(metadata_raw[128:192]),
        "language": _read_text(metadata_raw[224:240]),
        "created": created,
    }
    return metadata, pages, chapters
