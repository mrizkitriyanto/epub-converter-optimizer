import pytest

from eco.book import Block, Book
from eco.events import Finding
from eco.options import Options, image_profile, resolve_data_dir


def test_profiles():
    assert image_profile(Options(device="x4")) == image_profile(Options(device="x4-pro"))
    p = image_profile(Options(device="x3", size="balanced"))
    assert (p.max_w, p.max_h, p.grayscale, p.jpeg_quality) == (528, 792, True, 80)
    g = image_profile(Options(device="general", size="best"))
    assert (g.max_w, g.max_h, g.grayscale, g.jpeg_quality) == (2048, 2048, False, 92)
    assert image_profile(Options(device="x4", size="small", firmware="stock")).drop_images
    assert not image_profile(Options(device="x4", size="small", firmware="crosspoint")).drop_images


def test_profile_presets():
    assert image_profile(Options(device="general", size="small")).max_w == 1200
    assert image_profile(Options(device="general", size="balanced")).jpeg_quality == 85
    assert image_profile(Options(device="x4", size="small")).jpeg_quality == 65
    assert image_profile(Options(device="x4", size="best")).jpeg_quality == 92
    assert image_profile(Options(device="x4")).png_line_art
    assert not image_profile(Options(device="general", size="small", firmware="stock")).drop_images


def test_profile_min_px():
    assert image_profile(Options(device="x4")).min_px == 20
    assert image_profile(Options(device="x3")).min_px == 20
    assert image_profile(Options(device="general")).min_px == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("device", "kindle"),
        ("firmware", "custom"),
        ("formats", ("epub", "mobi")),
        ("size", "huge"),
        ("mode", "magic"),
        ("ocr", "maybe"),
    ],
)
def test_rejects_unknown_values(field, value):
    with pytest.raises(ValueError, match=str(value if isinstance(value, str) else value[1])):
        Options(**{field: value})


def test_rejects_unknown_device():
    with pytest.raises(ValueError):
        Options(device="kindle")


def test_data_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("ECO_DATA", str(tmp_path / "env"))
    assert resolve_data_dir(str(tmp_path / "cli")) == tmp_path / "cli"
    assert (tmp_path / "cli").is_dir()
    assert resolve_data_dir(None) == tmp_path / "env"
    assert (tmp_path / "env").is_dir()


def test_data_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ECO_DATA", raising=False)
    monkeypatch.setattr("platformdirs.user_data_dir", lambda app: str(tmp_path / app))
    assert resolve_data_dir(None) == tmp_path / "eco"
    assert (tmp_path / "eco").is_dir()


def test_model_defaults():
    b = Block("heading", "Bab 1", level=1, page=3)
    assert (b.bbox, b.html, b.image, b.caption, b.ocr) == (None, "", "", "", False)
    book = Book(title="T", language="id", blocks=[b])
    assert (book.author, book.source, book.cover, book.blocks) == ("", "", "", [b])
    assert Book(title="T").blocks == []
    assert Finding(1, "k", "info", "m").level == "info"
