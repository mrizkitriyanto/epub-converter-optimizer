import zipfile

import pytest
from fixtures.make import image_bytes, make_epub

from eco.bookfolder import load_source
from eco.cli import main
from eco.epub import zipio
from eco.epub.optimizer import DRMError, optimize_epub
from eco.epub.reader import epub_to_book
from eco.options import Options
from eco.render.md2typst import RenderSettings
from eco.render.pages import render_book

CONTAINER = (
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def tiny_epub(tmp_path, *bodies, extra=None, name="t.epub"):
    """An EPUB whose spine is one XHTML page per body, plus the files in `extra`."""
    items = "".join(
        f'<item id="c{n}" href="c{n}.xhtml" media-type="application/xhtml+xml"/>'
        for n in range(len(bodies))
    )
    refs = "".join(f'<itemref idref="c{n}"/>' for n in range(len(bodies)))
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Tiny</dc:title>'
        "<dc:creator>A. Author</dc:creator><dc:language>id</dc:language></metadata>"
        f"<manifest>{items}</manifest><spine>{refs}</spine></package>"
    )
    files = {"META-INF/container.xml": CONTAINER, "OEBPS/content.opf": opf}
    for n, body in enumerate(bodies):
        files[f"OEBPS/c{n}.xhtml"] = (
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
            f"<body>{body}</body></html>"
        )
    return make_epub(tmp_path / name, {**files, **(extra or {})})


def read(tmp_path, epub):
    folder = tmp_path / "out.book"
    findings = epub_to_book(epub, folder)
    return folder, findings, (folder / "book.md").read_text(encoding="utf-8")


def test_messy_epub_becomes_a_previewable_folder(messy_epub, tmp_path):
    folder, _, text = read(tmp_path, messy_epub)
    src = load_source(folder)
    assert src.meta["title"] == "Messy Book" and src.meta["language"] == "en"
    assert "\n# Chapter One" in text and "![" in text
    assert (folder / "images").is_dir() and any((folder / "images").iterdir())
    rendered = render_book(
        src, device="x4", settings=RenderSettings(), view="crosspoint", cache_dir=None
    )
    assert len(rendered.pages) >= 1


def test_element_mapping(tmp_path):
    epub = tiny_epub(
        tmp_path,
        "<h2>Head</h2><p>Plain <em>soft</em> and <strong>loud</strong> and "
        '<a href="x.xhtml#a">linked</a>.</p>'
        "<ul><li>one</li><li>two <ul><li>nested</li></ul></li></ul>"
        "<pre>a  b\n  c</pre><table><tr><td>1</td><td>x &amp; y</td></tr></table>",
    )
    folder, findings, text = read(tmp_path, epub)
    assert "## Head" in text
    assert "Plain *soft* and **loud** and [linked](x.xhtml#a)." in text
    assert "- one\n- two\n- nested" in text
    assert "```\na  b\n  c\n```" in text
    assert "<table>" in text and "<td>x &amp; y</td>" in text
    assert findings == []
    meta = (folder / "book.md").read_text(encoding="utf-8").split("---")[1]
    assert '"A. Author"' in meta and '"id"' in meta


def test_special_characters_are_escaped_once(tmp_path):
    epub = tiny_epub(tmp_path, "<p>2 * 3 &lt; 4 and a_b <em>x_y</em></p><p>1. not a list</p>")
    _, _, text = read(tmp_path, epub)
    assert r"2 \* 3 \< 4 and a\_b *x\_y*" in text
    assert r"1\. not a list" in text
    assert r"\\" not in text


def test_other_elements_are_flattened_and_counted(tmp_path):
    epub = tiny_epub(
        tmp_path,
        "<div>loose text</div><blockquote>quoted</blockquote><div><p>kept</p></div>",
    )
    _, findings, text = read(tmp_path, epub)
    assert "loose text\n\nquoted\n\nkept" in text
    assert [(f.kind, f.level) for f in findings] == [("flattened", "info")]
    assert "2 " in findings[0].message


def test_images_resolve_per_file_and_copy(tmp_path):
    extra = {
        "OEBPS/img/a.png": image_bytes((20, 20), "PNG"),
        "OEBPS/pics/a.png": image_bytes((30, 30), "PNG"),
    }
    epub = tiny_epub(
        tmp_path,
        '<p>before <img src="img/a.png" alt="first"/> after</p>',
        '<img src="pics/a%2Epng" alt="second"/>',
        extra=extra,
    )
    folder, findings, text = read(tmp_path, epub)
    assert text.count("![") == 2 and "before" in text and "after" in text
    assert sorted(p.name for p in (folder / "images").iterdir()) == ["a-1.png", "a.png"]
    assert findings == []


def test_image_outside_the_epub_is_refused(tmp_path):
    (tmp_path / "secret.png").write_bytes(image_bytes((20, 20), "PNG"))
    epub = tiny_epub(
        tmp_path,
        '<img src="../../secret.png" alt="x"/><img src="/etc/passwd" alt="y"/>',
        extra={"OEBPS/ok.png": image_bytes((20, 20), "PNG")},
    )
    folder, findings, text = read(tmp_path, epub)
    assert "![" not in text and not list((folder / "images").glob("*"))
    assert [f.kind for f in findings] == ["unsafe_path"]
    assert "2 " in findings[0].message


def test_missing_image_is_reported(tmp_path):
    epub = tiny_epub(tmp_path, '<img src="gone.png" alt="x"/><p>text</p>')
    _, findings, text = read(tmp_path, epub)
    assert "![" not in text and "text" in text
    assert [f.kind for f in findings] == ["missing_image"]


def test_drm_propagates(drm_epub, tmp_path):
    with pytest.raises(DRMError):
        epub_to_book(drm_epub, tmp_path / "out.book")


def bomb(tmp_path, monkeypatch):
    """A small zip whose directory adds up to more than the (lowered) cap."""
    monkeypatch.setattr(zipio, "MAX_EPUB_BYTES", 1000)
    return make_epub(tmp_path / "bomb.epub", {"a.bin": b"0" * 600, "b.bin": b"0" * 600})


def test_epub_reader_refuses_an_oversized_archive(tmp_path, monkeypatch):
    epub = bomb(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EPUB expands to more than 1 GiB: bomb.epub"):
        epub_to_book(epub, tmp_path / "out.book")
    assert not (tmp_path / "out.book").exists()


def test_optimizer_refuses_an_oversized_archive(tmp_path, monkeypatch):
    epub = bomb(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EPUB expands to more than 1 GiB: bomb.epub"):
        optimize_epub(epub, tmp_path / "o.epub", Options())


def test_cap_is_checked_before_any_entry_is_read(tmp_path, monkeypatch):
    epub = bomb(tmp_path, monkeypatch)

    def fail(self, *args, **kwargs):
        raise AssertionError("an entry was read")

    monkeypatch.setattr(zipfile.ZipFile, "read", fail)
    with pytest.raises(ValueError, match="1 GiB"):
        epub_to_book(epub, tmp_path / "out.book")


def test_cap_is_one_gibibyte():
    assert zipio.MAX_EPUB_BYTES == 2**30


def test_cli_reports_an_oversized_epub_as_one_error_line(tmp_path, monkeypatch, capsys):
    epub = bomb(tmp_path, monkeypatch)
    assert main(["convert", str(epub), "--data", str(tmp_path / "d")]) == 1
    err = capsys.readouterr().err
    assert err.strip().endswith("error: EPUB expands to more than 1 GiB: bomb.epub")
