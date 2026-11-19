import struct

from eco.xtc.container import Chapter, read_container, write_container


def container(**overrides) -> bytes:
    args = {
        "pages": [b"page one", b"page two"],
        "hq": True,
        "width": 480,
        "height": 800,
        "title": "A book",
        "author": "An author",
        "language": "en",
        "chapters": [Chapter("First", 0, 0), Chapter("Second", 1, 1)],
        "created": 123,
    }
    args.update(overrides)
    return write_container(**args)


def test_header_offsets_and_one_based_chapter_pages():
    data = container()

    assert data[:4] == b"XTCH"
    assert data[4:6] == b"\x01\x00"
    assert struct.unpack_from("<H", data, 6)[0] == 2
    assert struct.unpack_from("<Q", data, 16)[0] == 56
    assert struct.unpack_from("<Q", data, 48)[0] == 312
    assert struct.unpack_from("<H", data, 312 + 80)[0] == 1
    assert struct.unpack_from("<H", data, 312 + 82)[0] == 1


def test_long_utf8_fields_end_at_character_boundary_and_are_nul_terminated():
    data = container(title="Ü" * 200, chapters=[Chapter("—" * 100, 0, 1)])

    title = data[56 : 56 + 128]
    chapter = data[312 : 312 + 80]

    assert title[-1] == 0
    assert chapter[-1] == 0
    assert title.rstrip(b"\0").decode("utf-8") == "Ü" * 63
    assert chapter.rstrip(b"\0").decode("utf-8") == "—" * 26


def test_round_trip_returns_metadata_pages_and_chapters():
    raw = container(hq=False)

    metadata, pages, chapters = read_container(raw)

    assert metadata == {
        "hq": False,
        "width": 480,
        "height": 800,
        "title": "A book",
        "author": "An author",
        "language": "en",
        "created": 123,
    }
    assert pages == [b"page one", b"page two"]
    assert chapters == [Chapter("First", 0, 0), Chapter("Second", 1, 1)]


def test_page_index_stores_absolute_offset_size_and_dimensions():
    data = container()
    index_offset = struct.unpack_from("<Q", data, 24)[0]
    data_offset = struct.unpack_from("<Q", data, 32)[0]

    assert struct.unpack_from("<QIHH", data, index_offset) == (data_offset, 8, 480, 800)
    assert struct.unpack_from("<QIHH", data, index_offset + 16) == (
        data_offset + 8,
        8,
        480,
        800,
    )
