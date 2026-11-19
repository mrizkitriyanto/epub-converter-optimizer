from eco.font_coverage import missing_characters
from eco.options import Options
from eco.pipeline import convert_file
from eco.style import PageStyle


def test_missing_characters_counts_body_text_once():
    finding = missing_characters("# 😀\n\nHello 😀 😀 world.\n", PageStyle())
    assert finding is not None
    assert finding.kind == "font_fallback"
    assert "1 characters" in finding.message
    assert "😀" in finding.message


def test_heading_does_not_trigger_font_warning():
    assert missing_characters("# 😀\n\nHello world.\n", PageStyle()) is None


def test_xtc_conversion_reports_missing_character(tmp_path):
    book = tmp_path / "book.md"
    book.write_text("# A\n\nHello 😀 world.\n", encoding="utf-8")
    result = convert_file(
        book, Options(formats=("xtch",)), tmp_path / "out", data_dir=tmp_path / "data"
    )
    assert any(finding.kind == "font_fallback" for finding in result.findings)
