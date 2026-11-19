from fastapi.testclient import TestClient

from eco.cli import main
from eco.saved_styles import (
    delete_style,
    get_default,
    list_styles,
    load_style,
    save_style,
    set_default,
)
from eco.style import PageStyle


def test_save_load_default_delete(tmp_path):
    saved = save_style(tmp_path, "Night reading", {"margin": 24, "font_size": 40})
    assert (saved.margin_x, saved.margin_y) == (24, 24)
    assert load_style(tmp_path, "night reading") == saved
    set_default(tmp_path, "Night reading")
    assert get_default(tmp_path) == "Night reading"
    assert list_styles(tmp_path)[0]["default"]
    delete_style(tmp_path, "Night reading")
    assert get_default(tmp_path) is None


def test_cli_uses_default_style(tmp_path, capsys):
    save_style(tmp_path, "Night", {"font_size": 40})
    set_default(tmp_path, "Night")
    book = tmp_path / "a.md"
    book.write_text("# A\n\nText.\n")
    assert main(["convert", str(book), "--data", str(tmp_path)]) == 0
    assert "Style: Night (default)" in capsys.readouterr().out


def test_cli_unknown_style_lists_saved_names(tmp_path, capsys):
    save_style(tmp_path, "Night", {"font_size": 40})
    book = tmp_path / "a.md"
    book.write_text("# A\n\nText.\n")
    assert main(["convert", str(book), "--data", str(tmp_path), "--style", "Missing"]) == 1
    assert "Available styles: Night" in capsys.readouterr().err


def test_style_api(tmp_path):
    from eco.web.app import create_app

    client = TestClient(create_app(tmp_path, token=None), base_url="http://127.0.0.1:8000")
    assert client.put("/api/styles/Night", json={"margin": 20}).status_code == 200
    assert client.get("/api/styles/Night").json()["margin_x"] == 20
    assert client.put("/api/styles/Night/default").status_code == 200
    assert client.get("/api/styles").json()[0]["default"]
    assert client.delete("/api/styles/Night").status_code == 204


def test_new_job_keeps_saved_default_with_partial_options(tmp_path):
    from eco.web.app import _options

    save_style(tmp_path, "Night", {"font_size": 40, "margin_x": 25})
    set_default(tmp_path, "Night")
    default = load_style(tmp_path, get_default(tmp_path))
    assert _options(b'{"formats":["xtch"]}', default_style=default).style == default
    changed = _options(b'{"style":{"font_size":42}}', default_style=default).style
    assert (changed.font_size, changed.margin_x) == (42, 25)


def test_stored_style_survives_removed_font(tmp_path):
    folder = tmp_path / "styles"
    folder.mkdir()
    (folder / "Old.json").write_text(
        '{"font":"Removed Font","font_weight":700,"focus_mode":true}', encoding="utf-8"
    )
    findings = []
    style = load_style(tmp_path, "Old", findings=findings)
    assert style == PageStyle(font="Literata", font_weight=700)
    assert [finding.kind for finding in findings] == ["font_missing", "focus_unavailable"]
