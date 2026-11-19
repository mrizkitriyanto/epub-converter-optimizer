import zipfile
from io import BytesIO

from PIL import Image

from eco.xtc.codec import decode_page
from eco.xtc.container import read_container
from eco.xtc.devcheck import main


def test_device_check_kit(tmp_path):
    assert main([str(tmp_path)]) == 0

    assert {path.name for path in tmp_path.iterdir()} == {
        "gray-ramp.xtch",
        "chapters.xtc",
        "css-check.epub",
    }
    metadata, pages, chapters = read_container((tmp_path / "gray-ramp.xtch").read_bytes())
    assert metadata["hq"] is True
    assert len(pages) == 3
    assert [chapter.title for chapter in chapters] == ["One", "Two", "Three"]
    assert [chapter.start for chapter in chapters] == [0, 1, 2]

    image = decode_page(pages[0])
    y = image.height - 1
    assert [image.getpixel((image.width * n // 8, y)) for n in (1, 3, 5, 7)] == [
        255,
        170,
        85,
        0,
    ]


def test_css_check_has_split_chapter_table_code_and_images(tmp_path):
    main([str(tmp_path)])

    with zipfile.ZipFile(tmp_path / "css-check.epub") as book:
        xhtml = {name: book.read(name) for name in book.namelist() if name.endswith(".xhtml")}
        body = b"\n".join(xhtml.values())
        large = [name for name in xhtml if "/ch002" in name]
        images = [book.read(name) for name in book.namelist() if "/images/img-" in name]

    assert b"x" * 160 in body
    assert b"<table" in body
    assert len(large) >= 2
    assert len(images) == 2
    assert {Image.open(BytesIO(data)).format for data in images} == {"JPEG", "PNG"}
