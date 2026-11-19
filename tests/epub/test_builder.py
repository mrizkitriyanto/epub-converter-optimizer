import base64
import io
import os
import random
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

import pytest
from PIL import Image

from eco.book import Block, Book
from eco.bookfolder import load_source, write_book
from eco.epub.builder import _Builder, build_epub
from eco.epub.zipio import write_epub_zip
from eco.options import CHAPTER_LIMIT_BYTES

OPF = "OEBPS/content.opf"
NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "h": "http://www.w3.org/1999/xhtml",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
MEDIA = {
    ".xhtml": "application/xhtml+xml",
    ".ncx": "application/x-dtbncx+xml",
    ".css": "text/css",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}
RICH = """\
---
title: "Rich Book"
author: "Jane Doe"
---

Text before the first chapter.

# One

Some *emphasis*, **strong**, `code`, a [link](https://example.com) and a note.[^1]

## Section 1.1

| Name | Value |
|:-----|------:|
| a    | 1     |

```python
print("<b>&</b>")
```

A line<br>break, caf&eacute; &copy; 2026 and a picture:

<figure><img src="pic.png" alt="A figure"/><figcaption>Caption &amp; more</figcaption></figure>

<p class="footnote">A small-text note.</p>

- one
- two

> quote

# Two

## Section 2.1

Closing text.

[^1]: The footnote text.
"""


def long_markdown() -> str:
    paragraphs = [f"Paragraph {n}. " + "word " * 200 for n in range(150)]
    first, last = "\n\n".join(paragraphs[:100]), "\n\n".join(paragraphs[100:])
    return f"<!-- page: 5 -->\n\n# Big\n\n{first}\n\n## Late\n\n{last}\n"


def build(tmp_path, markdown, device="general", dst="x.epub"):
    md = tmp_path / "x.md"
    md.write_text(markdown, encoding="utf-8")
    findings = build_epub(load_source(md), tmp_path / dst, device=device)
    return zipfile.ZipFile(tmp_path / dst), findings


def build_book(tmp_path, folder, device):
    findings = build_epub(load_source(folder), tmp_path / "o.epub", device=device)
    return zipfile.ZipFile(tmp_path / "o.epub"), findings


def read_xml(z, name):
    return ET.fromstring(z.read(name))


def xhtml(z):
    return {n: z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml")}


def tag(name):
    return f"{{{NS['h']}}}{name}"


def test_zip_layout_and_chapters(tmp_path, small_book):
    dst = tmp_path / "o.epub"
    build_epub(load_source(small_book), dst, device="x4")
    z = zipfile.ZipFile(dst)
    first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert z.read("mimetype") == b"application/epub+zip"
    assert any(n.endswith("nav.xhtml") for n in z.namelist())
    assert sum(n.startswith("OEBPS/text/ch") for n in z.namelist()) == 2  # two "#" headings


def test_missing_image_is_a_finding(tmp_path):
    md = tmp_path / "x.md"
    md.write_text("# A\n\n![pic](nope.png)\n")
    findings = build_epub(load_source(md), tmp_path / "x.epub", device="general")
    assert [f.kind for f in findings] == ["missing_image"]


def test_every_xml_part_parses_and_has_the_xhtml_skeleton(tmp_path, small_book):
    z, _ = build_book(tmp_path, small_book, "x4")
    parts = [n for n in z.namelist() if n.endswith((".xhtml", ".opf", ".ncx", "container.xml"))]
    assert {"META-INF/container.xml", OPF, "OEBPS/toc.ncx", "OEBPS/nav.xhtml"} <= set(parts)
    for name in parts:
        read_xml(z, name)
    container = read_xml(z, "META-INF/container.xml")
    assert container.find(".//{*}rootfile").get("full-path") == OPF
    for name, text in xhtml(z).items():
        assert text.startswith('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html ')
        root = ET.fromstring(text)
        assert root.get("lang") == root.get(XML_LANG) == "en"
        assert root.findtext("h:head/h:title", namespaces=NS).strip()
        assert all(img.get("alt") is not None for img in root.iter(tag("img")))
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids)), name


def test_manifest_lists_every_file_and_the_spine_uses_it(tmp_path, small_book):
    z, _ = build_book(tmp_path, small_book, "x4")
    opf = read_xml(z, OPF)
    items = {i.get("href"): i for i in opf.iterfind(".//opf:item", NS)}
    assert {f"OEBPS/{h}" for h in items} == set(z.namelist()) - {
        "mimetype",
        OPF,
        "META-INF/container.xml",
    }
    for href, item in items.items():
        assert item.get("media-type") == MEDIA[Path(href).suffix]
    assert len({i.get("id") for i in items.values()}) == len(items)
    assert [i.get("href") for i in items.values() if i.get("properties") == "nav"] == ["nav.xhtml"]
    spine = opf.find("opf:spine", NS)
    assert spine.get("toc") == items["toc.ncx"].get("id")
    ids = {i.get("id"): h for h, i in items.items()}
    assert [ids[r.get("idref")] for r in spine] == [
        "text/cover.xhtml",
        "text/ch001.xhtml",
        "text/ch002.xhtml",
    ]


def test_real_cover_is_the_cover_image(tmp_path, small_book):
    z, _ = build_book(tmp_path, small_book, "x4")
    opf = read_xml(z, OPF)
    item = opf.find(".//opf:item[@properties='cover-image']", NS)
    assert item.get("id") == "cover-image" and item.get("media-type") == "image/png"
    assert z.read(f"OEBPS/{item.get('href')}") == (small_book / "images/cover.png").read_bytes()
    assert opf.find(".//opf:meta[@name='cover']", NS).get("content") == "cover-image"
    assert f"../{item.get('href')}" in xhtml(z)["OEBPS/text/cover.xhtml"]
    assert "OEBPS/images/cover.jpg" not in z.namelist()


def test_xteink_swaps_a_wide_table_for_its_image(tmp_path, small_book):
    z, findings = build_book(tmp_path, small_book, "x4")
    chapter = xhtml(z)["OEBPS/text/ch002.xhtml"]
    assert "<table" not in chapter
    src = re.search(r'<img src="\.\./(images/[^"]+)" alt="table" />', chapter)[1]
    assert z.read(f"OEBPS/{src}") == (small_book / "images/p0002-table-1.png").read_bytes()
    assert [(f.page, f.kind, f.level) for f in findings] == [(2, "table_as_image", "info")]


def test_general_keeps_the_wide_table_html(tmp_path, small_book):
    z, findings = build_book(tmp_path, small_book, "general")
    chapter = xhtml(z)["OEBPS/text/ch002.xhtml"]
    assert chapter.count("<table") == 1 and findings == []
    twin = (small_book / "images/p0002-table-1.png").read_bytes()
    assert twin not in [z.read(n) for n in z.namelist() if n.startswith("OEBPS/images/")]


def test_table_columns_count_colspan_and_narrow_tables_stay_html(tmp_path):
    for name in ("wide.png", "narrow.png"):
        Image.new("L", (40, 40)).save(tmp_path / name)
    md = (
        "# A\n\n<!-- page: 3 -->\n\n<!-- table-image: wide.png -->\n"
        '<table><tr><td colspan="5">a</td><td>b</td></tr></table>\n\n'
        "<!-- table-image: narrow.png -->\n"
        '<table><tr><td colspan="2">a</td><td>b</td><td>c</td></tr></table>\n'
    )
    z, findings = build(tmp_path, md, "x4")
    chapter = xhtml(z)["OEBPS/text/ch001.xhtml"]
    assert chapter.count("<table") == 1 and chapter.count("<img") == 1
    assert [(f.page, f.kind) for f in findings] == [(3, "table_as_image")]


def test_missing_table_image_keeps_the_table(tmp_path):
    md = "# A\n\n<!-- table-image: gone.png -->\n<table><tr>" + "<td>x</td>" * 6 + "</tr></table>\n"
    z, findings = build(tmp_path, md, "x4")
    assert xhtml(z)["OEBPS/text/ch001.xhtml"].count("<table") == 1
    assert [f.kind for f in findings] == ["missing_image"]


def test_page_markers_and_table_comments_are_dropped(tmp_path, small_book):
    z, _ = build_book(tmp_path, small_book, "general")
    assert all("<!--" not in text for text in xhtml(z).values())


def test_heading_ids_and_two_level_nav(tmp_path):
    z, _ = build(tmp_path, "# A\n\n## A1\n\n### A1a\n\n# B\n\n## B1\n")

    def heads(n):
        return re.findall(r'<h([1-6]) id="(h-\d+)"', xhtml(z)[f"OEBPS/text/ch00{n}.xhtml"])

    def sub(li):
        return [(a.text, a.get("href")) for a in li.findall("h:ol/h:li/h:a", NS)]

    assert heads(1) == [("1", "h-1"), ("2", "h-2"), ("3", "h-3")]
    assert heads(2) == [("1", "h-4"), ("2", "h-5")]

    nav = read_xml(z, "OEBPS/nav.xhtml")
    assert nav.find(".//h:nav", NS).get("{http://www.idpf.org/2007/ops}type") == "toc"
    top = nav.findall(".//h:nav/h:ol/h:li", NS)
    assert [li.findtext("h:a", namespaces=NS) for li in top] == ["A", "B"]
    assert sub(top[0]) == [("A1", "text/ch001.xhtml#h-2")]
    assert sub(top[1]) == [("B1", "text/ch002.xhtml#h-5")]

    ncx = read_xml(z, "OEBPS/toc.ncx")
    points = list(ncx.iter(f"{{{NS['ncx']}}}navPoint"))
    assert [p.findtext("ncx:navLabel/ncx:text", namespaces=NS) for p in points] == [
        "A",
        "A1",
        "B",
        "B1",
    ]
    assert [p.get("playOrder") for p in points] == ["1", "2", "3", "4"]
    assert len({p.get("id") for p in points}) == 4
    assert points[0].find("ncx:navPoint", NS) is points[1]
    assert points[1].find("ncx:content", NS).get("src") == "text/ch001.xhtml#h-2"
    assert ncx.find(".//ncx:meta[@name='dtb:depth']", NS).get("content") == "2"


def test_text_before_the_first_heading_goes_to_front(tmp_path):
    z, _ = build(tmp_path, "Intro text.\n\n## Early\n\n# A\n\nBody\n")
    assert "Intro text." in xhtml(z)["OEBPS/text/front.xhtml"]
    top = read_xml(z, "OEBPS/nav.xhtml").findall(".//h:nav/h:ol/h:li", NS)
    assert [li.findtext("h:a", namespaces=NS) for li in top] == ["x", "A"]
    assert top[0].find("h:a", NS).get("href") == "text/front.xhtml"
    assert top[0].find("h:ol/h:li/h:a", NS).get("href") == "text/front.xhtml#h-1"
    z, _ = build(tmp_path, "# A\n", dst="y.epub")
    assert "OEBPS/text/front.xhtml" not in z.namelist()


def test_text_that_xml_cannot_hold_becomes_u_fffd_with_a_finding_for_each_chapter(tmp_path):
    bad = "\ufffe\uffff\x01\x08"  # what XML 1.0 has no place for, even as a reference
    markdown = (
        '---\ntitle: "T\\f"\n---\n'
        f"# A\x0cB\n\nform{bad}feed and \x00 nul\n\n"
        "```\n0010 75 2D @.+.w......f#.u\ufffe\n```\n\n"
        "# Clean\n\nNothing here.\n\n"
        "# Raw\n\n<p>raw \uffff</p>\n\nsee &#xFFFE; and &#1;[^n]\n\n"
        "[^n]: a note in the footnote block, at the end \ufffe\n"
    )
    z, findings = build(tmp_path, markdown)
    for name in z.namelist():
        if name.endswith((".xhtml", ".opf", ".ncx")):
            read_xml(z, name)  # every one parses
    first = read_xml(z, "OEBPS/text/ch001.xhtml")
    assert "form\ufffd\ufffd\ufffd\ufffdfeed and \ufffd nul" in "".join(first.itertext())
    assert first.find(".//h:pre/h:code", NS).text == "0010 75 2D @.+.w......f#.u\ufffd\n"
    assert read_xml(z, OPF).find(".//dc:title", NS).text == "T\ufffd"
    replaced = "that XML cannot hold replaced with U+FFFD in"
    assert [(f.kind, f.level, f.message) for f in findings] == [
        ("xml_char_replaced", "warning", f"1 character {replaced} the book's metadata"),
        ("xml_char_replaced", "warning", f"7 characters {replaced} chapter 'A\ufffdB'"),
        ("xml_char_replaced", "warning", f"2 characters {replaced} chapter 'Raw'"),
    ]


def test_thematic_breaks_at_the_start_are_content_not_front_matter(tmp_path):
    md = "---\ntitle: T\n---\n\n---\n\nPreface text\n\n---\n\n# A\n\nBody\n"
    z, findings = build(tmp_path, md)
    assert findings == []
    front = xhtml(z)["OEBPS/text/front.xhtml"]
    assert "<p>Preface text</p>" in front and front.count("<hr />") == 2
    opf = read_xml(z, OPF)
    hrefs = {i.get("id"): i.get("href") for i in opf.iterfind(".//opf:item", NS)}
    for ref in opf.iterfind(".//opf:itemref", NS):
        body = read_xml(z, f"OEBPS/{hrefs[ref.get('idref')]}").find("h:body", NS)
        assert len(body), ref.get("idref")  # no blank page in the spine


def test_a_block_that_renders_to_nothing_does_not_add_a_front_page(tmp_path):
    z, findings = build(tmp_path, '<img src="gone.png" alt="x"/>\n\n# A\n\nBody\n')
    assert [f.kind for f in findings] == ["missing_image"]
    assert "OEBPS/text/front.xhtml" not in z.namelist()


def test_empty_markdown_still_has_a_navigable_package(tmp_path):
    z, findings = build(tmp_path, "")
    assert findings == [] and "OEBPS/text/front.xhtml" in z.namelist()
    assert len(read_xml(z, "OEBPS/nav.xhtml").findall(".//h:nav/h:ol/h:li", NS)) == 1


def test_long_chapter_is_split_at_block_boundaries(tmp_path):
    z, findings = build(tmp_path, long_markdown())
    parts = {n: t for n, t in xhtml(z).items() if "/ch001" in n}
    assert len(parts) >= 2
    assert all(len(t.encode()) <= CHAPTER_LIMIT_BYTES for t in parts.values())
    assert sum(t.count("<p>") for t in parts.values()) == 150
    assert [(f.page, f.kind, f.level) for f in findings] == [(5, "chapter_split", "info")]
    late = read_xml(z, "OEBPS/nav.xhtml").find(".//h:li/h:ol/h:li/h:a", NS)
    name, fragment = late.get("href").split("#")
    assert name != "text/ch001.xhtml" and f'id="{fragment}"' in z.read(f"OEBPS/{name}").decode()
    spine = [r.get("idref") for r in read_xml(z, OPF).iterfind(".//opf:itemref", NS)]
    assert spine[:3] == ["cover", "ch001", "ch001-2"]


def test_footnote_links_follow_their_target_to_another_file(tmp_path):
    z, _ = build(tmp_path, "# A\n\nText[^1]\n\n# B\n\nMore.\n\n[^1]: The note.\n")
    one, two = (xhtml(z)[f"OEBPS/text/ch00{n}.xhtml"] for n in (1, 2))
    assert 'href="ch002.xhtml#fn1"' in one and 'id="fn1"' in two
    assert 'href="ch001.xhtml#fnref1"' in two and 'id="fnref1"' in one


def test_malformed_raw_html_is_kept_as_text(tmp_path):
    z, findings = build(tmp_path, '<!-- page: 4 -->\n\n# A\n\n<div class="x">unclosed\n\nplain\n')
    assert [(f.page, f.kind, f.level) for f in findings] == [(4, "bad_html", "warning")]
    root = read_xml(z, "OEBPS/text/ch001.xhtml")
    assert [p.text for p in root.iter(tag("p"))] == ['<div class="x">unclosed', "plain"]


def test_malformed_heading_keeps_its_id_for_the_nav(tmp_path):
    z, findings = build(tmp_path, "# A <b>bold\n\ntext\n")
    assert [f.kind for f in findings] == ["bad_html"]
    root = read_xml(z, "OEBPS/text/ch001.xhtml")
    assert next(root.iter(tag("p"))).get("id") == "h-1"
    link = read_xml(z, "OEBPS/nav.xhtml").find(".//h:nav/h:ol/h:li/h:a", NS)
    assert (link.text, link.get("href")) == ("A bold", "text/ch001.xhtml")


def test_html_void_tags_and_named_entities_become_xml(tmp_path):
    Image.new("L", (30, 30)).save(tmp_path / "pic.png")
    md = (
        '# A\n\nLine<br>break <img src="pic.png"> inline.\n\n'
        "<div>caf&eacute; &copy; &amp; &lt;b&gt; &bogus;<hr></div>\n"
    )
    z, findings = build(tmp_path, md)
    assert findings == []
    text = xhtml(z)["OEBPS/text/ch001.xhtml"]
    assert "<br />" in text and "<hr />" in text
    root = ET.fromstring(text)
    assert "café © & <b> &bogus;" in "".join(root.itertext())
    assert next(root.iter(tag("img"))).get("alt") == ""


def test_bare_ampersands_in_raw_html_are_escaped(tmp_path):
    md = (
        "# A\n\n<table><tr><td>R&D</td><td>AT&T</td></tr></table>\n\n"
        '<p><a href="https://example.com/?a=1&b=2&copy=3">x&#169;y &copy; &amp; &bogus;</a></p>\n'
    )
    z, findings = build(tmp_path, md)
    assert findings == []
    root = read_xml(z, "OEBPS/text/ch001.xhtml")
    assert [td.text for td in root.iter(tag("td"))] == ["R&D", "AT&T"]
    link = next(root.iter(tag("a")))
    assert link.get("href") == "https://example.com/?a=1&b=2&copy=3"
    assert link.text == "x©y © & &bogus;"


def test_images_get_safe_names_and_manifest_entries(tmp_path):
    folder = tmp_path / "my book"
    (folder / "images dir").mkdir(parents=True)
    for name in ("my pic.png", "ü.jpg"):
        Image.new("L", (30, 30)).save(folder / "images dir" / name)
    (folder / "book.md").write_text(
        "# A\n\n![a](<images dir/my pic.png>)\n\n![again](<images dir/my pic.png>)\n\n"
        '<img src="images dir/ü.jpg" alt="u"/>\n',
        encoding="utf-8",
    )
    z, findings = build_book(tmp_path, folder, "general")
    assert findings == []
    assert all(n.isascii() and " " not in n for n in z.namelist())
    assert [n for n in z.namelist() if n.startswith("OEBPS/images/")] == [
        "OEBPS/images/cover.jpg",
        "OEBPS/images/img-001.png",
        "OEBPS/images/img-002.jpg",
    ]
    assert xhtml(z)["OEBPS/text/ch001.xhtml"].count('src="../images/img-001.png"') == 2
    items = {
        i.get("href"): i.get("media-type") for i in read_xml(z, OPF).iterfind(".//opf:item", NS)
    }
    assert (
        items["images/img-001.png"] == "image/png" and items["images/img-002.jpg"] == "image/jpeg"
    )


def test_image_outside_the_book_folder_is_refused(tmp_path):
    Image.new("L", (30, 30)).save(tmp_path / "secret.png")
    folder = tmp_path / "book"
    folder.mkdir()
    absolute = (tmp_path / "secret.png").as_posix()
    (folder / "x.md").write_text(f'# A\n\n![s](../secret.png)\n\n<img src="{absolute}" alt=""/>\n')
    findings = build_epub(load_source(folder / "x.md"), tmp_path / "o.epub", device="general")
    assert [f.kind for f in findings] == ["missing_image", "missing_image"]
    assert not [n for n in zipfile.ZipFile(tmp_path / "o.epub").namelist() if "img-" in n]


def test_data_uri_images_are_left_for_the_optimizer(tmp_path):
    png = io.BytesIO()
    Image.new("L", (30, 30)).save(png, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
    z, findings = build(tmp_path, f"# A\n\n![x]({uri})\n")
    assert findings == [] and f'src="{uri}"' in xhtml(z)["OEBPS/text/ch001.xhtml"]


@pytest.mark.parametrize(
    ("device", "size"), [("x4", (480, 800)), ("x3", (528, 792)), ("general", (1200, 1600))]
)
def test_text_cover_when_the_book_has_none(tmp_path, device, size):
    title = "A Very Long Title For The Cover Page Of This Book"
    z, findings = build(tmp_path, f'---\ntitle: "{title}"\nauthor: "Jane Doe"\n---\n# A\n', device)
    assert findings == []
    cover = Image.open(io.BytesIO(z.read("OEBPS/images/cover.jpg")))
    assert (cover.format, cover.size) == ("JPEG", size) and not cover.info.get("progressive")
    gray = cover.convert("L")
    width, height = size
    assert gray.getpixel((2, 2)) > 240 and gray.getextrema()[0] < 100  # white page, black text
    margins = [(0, 0, width // 20, height), (width - width // 20, 0, width, height)]
    assert all(gray.crop(box).getextrema()[0] > 200 for box in margins)  # the title is wrapped
    opf = read_xml(z, OPF)
    item = opf.find(".//opf:item[@properties='cover-image']", NS)
    assert (item.get("href"), item.get("media-type")) == ("images/cover.jpg", "image/jpeg")
    assert opf.find(".//opf:itemref", NS).get("idref") == "cover"
    assert 'src="../images/cover.jpg"' in xhtml(z)["OEBPS/text/cover.xhtml"]


def test_missing_cover_is_a_finding_and_gets_a_text_cover(tmp_path):
    z, findings = build(tmp_path, '---\ntitle: "T"\ncover: "nope.png"\n---\n# A\n')
    assert [(f.page, f.kind) for f in findings] == [(0, "missing_image")]
    assert "OEBPS/images/cover.jpg" in z.namelist()


def test_package_metadata(tmp_path):
    z, _ = build(tmp_path, '---\ntitle: "T & U"\nauthor: "Jane"\nlanguage: "id"\n---\n# A\n')
    opf = read_xml(z, OPF)
    identifier = opf.find(".//dc:identifier", NS)
    assert opf.get("version") == "3.0" and opf.get("unique-identifier") == identifier.get("id")
    assert opf.findtext(".//dc:title", namespaces=NS) == "T & U"
    assert opf.findtext(".//dc:creator", namespaces=NS) == "Jane"
    assert opf.findtext(".//dc:language", namespaces=NS) == "id"
    modified = opf.findtext(".//opf:meta[@property='dcterms:modified']", namespaces=NS)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", modified)
    assert read_xml(z, "OEBPS/text/ch001.xhtml").get("lang") == "id"
    z, _ = build(tmp_path, "# A\n", dst="y.epub")
    opf = read_xml(z, OPF)
    assert opf.find(".//dc:creator", NS) is None
    assert opf.findtext(".//dc:language", namespaces=NS) == "en"


def test_identifier_is_stable_across_builds(tmp_path):
    def identifier(markdown, dst):
        z, _ = build(tmp_path, markdown, dst=dst)
        uid = read_xml(z, OPF).findtext(".//dc:identifier", namespaces=NS)
        ncx = read_xml(z, "OEBPS/toc.ncx")
        assert ncx.find(".//ncx:meta[@name='dtb:uid']", NS).get("content") == uid
        return uid

    def urn(name):
        return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, name))

    assert identifier("# A\n", "1.epub") == identifier("# A\n", "2.epub") == urn("x")
    with_source = '---\ntitle: "T"\nsource: "book.pdf sha256:abc"\n---\n# A\n'
    assert identifier(with_source, "3.epub") == urn("book.pdf sha256:abc")


def test_footnote_paragraphs_are_styled_small(tmp_path):
    z, _ = build(tmp_path, '# A\n\n<p class="footnote">note &amp; more</p>\n')
    assert "p.footnote" in z.read("OEBPS/style.css").decode()
    chapter = xhtml(z)["OEBPS/text/ch001.xhtml"]
    assert '<p class="footnote">note &amp; more</p>' in chapter
    assert 'href="../style.css"' in chapter


def test_rich_markdown_builds_well_formed_files(tmp_path):
    Image.new("L", (30, 30)).save(tmp_path / "pic.png")
    z, findings = build(tmp_path, RICH)
    assert findings == []
    for name in z.namelist():
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            read_xml(z, name)
    assert "OEBPS/text/front.xhtml" in z.namelist()
    assert "<table>" in xhtml(z)["OEBPS/text/ch001.xhtml"]


def test_write_epub_zip_layout(tmp_path):
    rng = random.Random(3)
    base = bytearray(rng.choices(b"abcdefghijklmnopqrstuvwxyz ", k=500))
    data = bytearray()
    for _ in range(150):  # near-repeats of one block: level 9 packs these tighter than level 6
        copy = bytearray(base)
        for _ in range(5):
            copy[rng.randrange(500)] = rng.choice(b"abcdefghijklmnopqrstuvwxyz ")
        data += copy
    data = bytes(data)
    dst = tmp_path / "o.epub"
    write_epub_zip(dst, {"OEBPS/b.txt": data, "OEBPS/a.txt": b"a", "mimetype": b"wrong"})
    z = zipfile.ZipFile(dst)
    assert z.namelist() == ["mimetype", "OEBPS/a.txt", "OEBPS/b.txt"]
    infos = z.infolist()
    assert z.read("mimetype") == b"application/epub+zip" and not infos[0].extra
    assert infos[0].compress_type == zipfile.ZIP_STORED
    assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in infos[1:])

    def raw_deflate(level):
        packer = zlib.compressobj(level, zlib.DEFLATED, -15)
        return len(packer.compress(data) + packer.flush())

    assert raw_deflate(9) < raw_deflate(6)
    assert z.getinfo("OEBPS/b.txt").compress_size == raw_deflate(9)


def test_write_epub_zip_drops_os_junk(tmp_path):
    junk = [".DS_Store", "OEBPS/.DS_Store", "Thumbs.db", "OEBPS/thumbs.db", "desktop.ini"]
    junk += ["__MACOSX/a", "OEBPS/__MACOSX/b"]
    dst = tmp_path / "o.epub"
    write_epub_zip(dst, {n: b"x" for n in ["OEBPS/ok.txt", *junk]})
    assert zipfile.ZipFile(dst).namelist() == ["mimetype", "OEBPS/ok.txt"]


def test_epubcheck_export(tmp_path, small_book):
    out = os.environ.get("ECO_EPUBCHECK_DIR")
    if not out:
        pytest.skip("ECO_EPUBCHECK_DIR is not set")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for device in ("x4", "general"):
        build_epub(load_source(small_book), out / f"small-{device}.epub", device=device)
    Image.new("L", (30, 30)).save(tmp_path / "pic.png")
    for name, markdown, device in (("rich", RICH, "general"), ("split", long_markdown(), "x4")):
        (tmp_path / f"{name}.md").write_text(markdown, encoding="utf-8")
        build_epub(load_source(tmp_path / f"{name}.md"), out / f"{name}.epub", device=device)


def test_the_page_of_a_chapter_with_replaced_characters_is_not_left_for_later_findings(tmp_path):
    md = tmp_path / "x.md"
    md.write_text(
        "<!-- page: 3 -->\n\n# A\n\nbad \ufffe\n\n# B\n\n<!-- page: 9 -->\n\nok\n", encoding="utf-8"
    )
    builder = _Builder(load_source(md), "general")
    builder._chapters()
    assert [(f.kind, f.page) for f in builder.findings] == [("xml_char_replaced", 3)]
    assert builder.page == 9  # where the text ended, as before the findings


def numbered(*items):
    """A paragraph, then one list item per (number, text)."""
    return [Block("paragraph", "Next:", page=1)] + [
        Block("list_item", text, number=n, page=1) for n, text in items
    ]


def test_numbered_list_items_become_ordered_lists_that_keep_their_start(tmp_path):
    blocks = [
        Block("heading", "H", level=1, page=1),
        Block("list_item", "first", number=3, page=1),
        Block("list_item", "second\nline", number=4, page=1),
        Block("list_item", "A. a lettered item", page=1),
        Block("list_item", "fifth", number=5, page=1),
        *numbered((1, "a"), (2, "b"), (1, "c"), (2, "d"), (3, "e")),  # a list that starts again
        *numbered((5, "f"), (7, "g")),  # a number skipped
        *numbered((0, "h"), (1, "i")),  # a list that starts at 0
        *numbered((3, "j"), (4, "k"), (5, "l")),
    ]
    folder = tmp_path / "n.book"
    write_book(Book(title="T", blocks=blocks), folder, [])
    markdown = load_source(folder).markdown
    assert "3. first\n4. second\n   line\n\n- A. a lettered item\n\n5. fifth" in markdown
    z, _ = build_book(tmp_path, folder, "general")
    body = read_xml(z, "OEBPS/text/ch001.xhtml")
    lists = [
        (
            el.tag.split("}")[1],
            el.get("start"),
            [" ".join("".join(li.itertext()).split()) for li in el],
        )
        for el in body.iter()
        if el.tag in (tag("ol"), tag("ul"))
    ]
    assert lists == [
        ("ol", "3", ["first", "second line"]),
        ("ul", None, ["A. a lettered item"]),
        ("ol", "5", ["fifth"]),
        ("ol", None, ["a", "b"]),
        ("ol", None, ["c", "d", "e"]),
        ("ol", "5", ["f"]),
        ("ol", "7", ["g"]),
        ("ol", "0", ["h", "i"]),
        ("ol", "3", ["j", "k", "l"]),
    ]
