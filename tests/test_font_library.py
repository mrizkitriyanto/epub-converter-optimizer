import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont

from eco.cli import main
from eco.font_library import MAX_FONT_BYTES, add_font, list_fonts, remove_font
from eco.style import FONTS_DIR
from eco.web.app import create_app


def test_invalid_font_is_rejected_by_cli_and_api(tmp_path, capsys):
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not a font")
    assert main(["fonts", "--data", str(tmp_path), "add", str(bad)]) == 1
    assert "Not a usable font file" in capsys.readouterr().err
    client = TestClient(create_app(tmp_path, token=None), base_url="http://127.0.0.1:8000")
    response = client.post("/api/fonts", files=[("files", ("bad.ttf", b"bad"))])
    assert response.status_code == 400
    assert list_fonts(tmp_path) == []


def test_bundled_family_cannot_shadow_built_in(tmp_path):
    font = FONTS_DIR / "literata" / "Literata-Regular.ttf"
    with pytest.raises(ValueError, match="built-in font"):
        add_font(tmp_path, font.name, font.read_bytes())


def test_add_deduplicate_and_remove_family(tmp_path):
    source = FONTS_DIR / "literata" / "Literata-Regular.ttf"
    custom = tmp_path / "custom.ttf"
    with TTFont(source) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6, 16):
                record.string = "Test Reader".encode(record.getEncoding())
        font.save(custom)
    content = custom.read_bytes()
    assert add_font(tmp_path, custom.name, content)["status"] == "added"
    assert add_font(tmp_path, custom.name, content)["status"] == "unchanged"
    with TTFont(custom) as font:
        font["name"].setName("Version 2", 5, 3, 1, 0x409)
        font.save(custom)
    assert add_font(tmp_path, custom.name, custom.read_bytes())["status"] == "replaced"
    assert list_fonts(tmp_path)[0]["family"] == "Test Reader"
    assert remove_font(tmp_path, "Test Reader") == 1
    assert list_fonts(tmp_path) == []


def test_font_size_limit(tmp_path):
    with pytest.raises(ValueError, match="Not a usable font file"):
        add_font(tmp_path, "huge.ttf", b"x" * (MAX_FONT_BYTES + 1))
