import xml.etree.ElementTree as ET

from eco.epub.toc import (
    TocEntry,
    broken_share,
    entries_from_nav,
    entries_from_ncx,
    headings,
    nav_body,
    ncx_map,
)

XHTML = "http://www.w3.org/1999/xhtml"


def xhtml(body: str, title: str = "T") -> ET.Element:
    return ET.fromstring(
        f'<html xmlns="{XHTML}"><head><title>{title}</title></head><body>{body}</body></html>'
    )


def test_headings_in_order_with_ids():
    a = xhtml("<h1>One</h1><p>x</p><h2 id='s'>Sub <b>part</b></h2><h4>Deep</h4>")
    b = xhtml("<h1>Two</h1>")
    entries = headings([("t/a.xhtml", a), ("t/b.xhtml", b)])
    assert [(e.level, e.label, e.path, e.anchor) for e in entries] == [
        (1, "One", "t/a.xhtml", "eco-toc-1"),
        (2, "Sub part", "t/a.xhtml", "s"),
        (1, "Two", "t/b.xhtml", "eco-toc-2"),
    ]
    assert a.find(f".//{{{XHTML}}}h1").get("id") == "eco-toc-1"


def test_no_headings_gives_one_entry_per_page():
    pages = [("t/a.xhtml", xhtml("<p>x</p>", "Start")), ("t/b.xhtml", xhtml("<p>y</p>", ""))]
    entries = headings(pages)
    assert [(e.label, e.anchor) for e in entries] == [("Start", ""), ("Section 2", "")]


def test_ncx_nests_by_level():
    entries = [TocEntry(1, "One", "t/a.xhtml", "a"), TocEntry(2, "Sub", "t/a.xhtml", "s")]
    nav_map = ncx_map(entries, "t/toc.ncx")
    outer = nav_map.find("{*}navPoint")
    assert outer.find("{*}navLabel/{*}text").text == "One"
    assert outer.find("{*}content").get("src") == "a.xhtml#a"
    assert outer.find("{*}navPoint/{*}navLabel/{*}text").text == "Sub"
    assert [
        p.get("playOrder") for p in nav_map.iter("{http://www.daisy.org/z3986/2005/ncx/}navPoint")
    ] == ["1", "2"]


def test_nav_nests_by_level():
    entries = [TocEntry(1, "One", "t/a.xhtml", ""), TocEntry(2, "Sub", "t/b.xhtml", "s")]
    nav = nav_body(entries, "nav.xhtml")
    assert nav.get("{http://www.idpf.org/2007/ops}type") == "toc"
    outer = nav.find("{*}ol/{*}li")
    assert outer.find("{*}a").get("href") == "t/a.xhtml"
    assert outer.find("{*}ol/{*}li/{*}a").get("href") == "t/b.xhtml#s"


def test_broken_share():
    assert broken_share(["a", "b", "c"], {"a"}.__contains__) == 2 / 3
    assert broken_share([], {"a"}.__contains__) == 0


def test_the_readers_give_back_what_was_written():
    entries = [
        TocEntry(1, "One", "t/a.xhtml", "a"),
        TocEntry(2, "Sub", "t/a.xhtml", "s"),
        TocEntry(1, "Two", "t/b.xhtml", ""),
    ]
    assert entries_from_ncx(ncx_map(entries, "toc.ncx"), "toc.ncx") == entries
    assert entries_from_nav(nav_body(entries, "nav.xhtml"), "nav.xhtml") == entries


def test_an_empty_label_is_named():
    ncx = ET.fromstring(
        '<navMap xmlns="http://www.daisy.org/z3986/2005/ncx/"><navPoint><navLabel><text></text>'
        '</navLabel><content src="a.xhtml"/></navPoint></navMap>'
    )
    assert [e.label for e in entries_from_ncx(ncx, "toc.ncx")] == ["Section 1"]
    nav = ET.fromstring(
        f'<nav xmlns="{XHTML}"><ol><li><a href="a.xhtml"><img src="m.png" alt="Map"/></a></li></ol></nav>'
    )
    assert [e.label for e in entries_from_nav(nav, "nav.xhtml")] == ["Map"]


def test_entries_under_an_unlinked_part_keep_its_level():
    nav = ET.fromstring(
        f'<nav xmlns="{XHTML}"><ol><li><a href="a.xhtml">One</a></li>'
        "<li><span>Part</span><ol><li><a href='b.xhtml'>Two</a></li></ol></li></ol></nav>"
    )
    assert [(e.level, e.label) for e in entries_from_nav(nav, "nav.xhtml")] == [
        (1, "One"),
        (1, "Two"),
    ]
