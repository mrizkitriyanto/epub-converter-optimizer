import pytest
from fastapi.testclient import TestClient

from eco.cli import main
from eco.font_library import add_font, list_fonts
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
