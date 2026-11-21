from dataclasses import replace

import numpy as np
import pytest

from eco import pipeline
from eco.bookfolder import load_source
from eco.cli import main
from eco.epub.validator import EpubValidationError
from eco.options import Options
from eco.pipeline import convert_file
from eco.render.pages import render_book
from eco.style import BUNDLED_FONTS, PageStyle
from eco.xtc.codec import decode_page
from eco.xtc.container import read_container
from eco.xtc.quantize import quantize_page


def convert(path, out, options):
    return convert_file(path, options, out, data_dir=out / "data")


def test_pipeline_writes_epub_and_exact_xtch_pages(tmp_path, small_book):
    style = PageStyle(bar_position="off")
    options = Options(device="x4", formats=("epub", "xtch", "xtc"), style=style)

    result = convert(small_book, tmp_path / "out", options)

    assert set(result.outputs) == {"epub", "xtch", "xtc"}
    assert result.outputs["epub"].name == "small.x4.epub"
    assert result.outputs["xtch"].name == "small.x4.xtch"
    rendered = render_book(
        load_source(small_book), device="x4", style=style, view="xtc", image_profile=None
    )
    for fmt, mode in (("xtch", "xth"), ("xtc", "xtg")):
        metadata, encoded, chapters = read_container(result.outputs[fmt].read_bytes())
        assert len(encoded) == len(rendered.pages)
        expected = quantize_page(
            rendered.pages[0], rendered.image_boxes[0], replace(style, mode=mode)
        )
        assert np.array_equal(np.asarray(decode_page(encoded[0])), np.asarray(expected))
        assert metadata["title"] == "Small Book"
        assert [(chapter.title, chapter.start) for chapter in chapters] == rendered.chapters


def test_invalid_epub_stops_mixed_format_file_before_xtc(tmp_path, small_book, monkeypatch):
    def reject(epub):
        raise EpubValidationError("EPUBCheck found errors")

    monkeypatch.setattr(pipeline, "validate_epub", reject, raising=False)
    out = tmp_path / "out"
    with pytest.raises(EpubValidationError, match="EPUBCheck found errors"):
        convert(small_book, out, Options(formats=("epub", "xtc")))
    assert not list(out.glob("*.epub"))
    assert not list(out.glob("*.xtc"))


def test_empty_markdown_writes_no_xtch(tmp_path):
    source = tmp_path / "empty.md"
    source.write_text("")
    out = tmp_path / "out"

    try:
        convert(source, out, Options(formats=("xtch",)))
    except ValueError as error:
        assert str(error) == "Nothing to render"
    else:
        raise AssertionError("empty Markdown should not render")
    assert not list(out.glob("*.xtch"))


def test_cli_accepts_format_list_and_style_file(tmp_path):
    source = tmp_path / "book.md"
    source.write_text("# One\n\n" + "Long text. " * 500)
    style = tmp_path / "style.json"
    style.write_text('{"font_size": 40}')

    default_out = tmp_path / "default"
    large_out = tmp_path / "large"
    common = [str(source), "--format", "xtch", "--data", str(tmp_path / "data")]
    assert main(["convert", *common, "-o", str(default_out)]) == 0
    assert main(["convert", *common, "-o", str(large_out), "--style", str(style)]) == 0
    _, default_pages, _ = read_container((default_out / "book.x4-pro.xtch").read_bytes())
    _, large_pages, _ = read_container((large_out / "book.x4-pro.xtch").read_bytes())
    assert len(large_pages) > len(default_pages)


def test_cli_font_path_and_size_override_style(monkeypatch, tmp_path):
    source = tmp_path / "book.md"
    source.write_text("# One\n")
    style = tmp_path / "style.json"
    style.write_text('{"font_size": 20}')
    font = BUNDLED_FONTS["Bitter"][400]
    seen = {}

    def fake(path, options, out, **kwargs):
        seen.update(options=options, dirs=kwargs["font_extra_dirs"])
        output = out / "book.x4.xtc"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"x")
        from eco.pipeline import Result

        return Result(path, {"xtc": output}, None, [], 0, {"xtc": 1})

    monkeypatch.setattr("eco.pipeline.convert_file", fake)
    assert (
        main(
            [
                "convert",
                str(source),
                "--format",
                "xtch,xtc",
                "--style",
                str(style),
                "--font",
                str(font),
                "--font-size",
                "36",
                "--data",
                str(tmp_path / "data"),
            ]
        )
        == 0
    )
    assert seen["options"].formats == ("xtch", "xtc")
    assert seen["options"].style == replace(PageStyle(font="Bitter", font_size=20), font_size=36)
    assert seen["dirs"] == (font.parent,)
