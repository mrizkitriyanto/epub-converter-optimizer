import base64
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import pytest
from fixtures.make import FONT_CHARS, image_bytes, make_epub, make_font
from fontTools.ttLib import TTFont
from PIL import Image

from eco.bookfolder import load_source
from eco.epub.builder import build_epub
from eco.epub.optimizer import DRMError, OptimizeReport, _unsafe_name, optimize_epub
from eco.options import CHAPTER_LIMIT_BYTES, Options

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "h": "http://www.w3.org/1999/xhtml",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
}
XHTML = "application/xhtml+xml"
MEDIA = {
    ".xhtml": XHTML,
    ".css": "text/css",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".smil": "application/smil+xml",
}
X4 = Options(device="x4")
GENERAL = Options(device="general")
LINK = '<link rel="stylesheet" href="../css/s.css"/>'  # keeps css/s.css referenced


def run(tmp_path, src, options=X4, dst="o.epub"):
    report = optimize_epub(src, tmp_path / dst, options)
    return zipfile.ZipFile(tmp_path / dst), report


def kinds(report):
    return [f.kind for f in report.findings]


def opf_of(z):
    container = ET.fromstring(z.read("META-INF/container.xml"))
    path = container.find(".//c:rootfile", NS).get("full-path")
    return path, ET.fromstring(z.read(path))


def manifest(z):
    """Zip path -> manifest item."""
    path, opf = opf_of(z)
    base = posixpath.dirname(path)
    return {
        posixpath.normpath(posixpath.join(base, unquote(i.get("href")))): i
        for i in opf.iterfind(".//opf:item", NS)
    }


def spine(z):
    """Zip paths of the spine, in order."""
    _, opf = opf_of(z)
    by_id = {i.get("id"): p for p, i in manifest(z).items()}
    return [by_id[r.get("idref")] for r in opf.iterfind(".//opf:itemref", NS)]


def text_of(z, name):
    return z.read(name).decode()


def tag(prefix, name):
    return f"{{{NS[prefix]}}}{name}"


def resolve(owner, ref):
    parts = urlsplit(ref)
    if parts.scheme or parts.netloc:
        return None, ""
    path = (
        owner if not parts.path else posixpath.join(posixpath.dirname(owner), unquote(parts.path))
    )
    return posixpath.normpath(path), parts.fragment


def ids_of(z, name):
    root = ET.fromstring(z.read(name))
    return {e.get("id") for e in root.iter() if e.get("id")} | {
        e.get("name") for e in root.iter(tag("h", "a")) if e.get("name")
    }


def check_package(z):
    """The output is a sound package: it parses, nothing it lists or links to is missing."""
    names = set(z.namelist())
    infos = z.infolist()
    assert infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED
    assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in infos[1:])
    assert not [n for n in names if re.search(r"(^|/)(\.DS_Store|Thumbs\.db|__MACOSX)", n)]
    items = manifest(z)
    assert set(items) <= names
    ids = [i.get("id") for i in items.values()]
    assert len(ids) == len(set(ids))
    _, opf = opf_of(z)
    for ref in opf.iterfind(".//opf:itemref", NS):
        assert ref.get("idref") in ids
    cover = opf.find(".//opf:meta[@name='cover']", NS)
    assert cover is None or cover.get("content") in ids
    for path, item in items.items():
        media = item.get("media-type")
        if media == XHTML:
            root = ET.fromstring(z.read(path))
            if "svg" not in (item.get("properties") or "").split():
                assert next(root.iter("{http://www.w3.org/2000/svg}svg"), None) is None, path
            for el in root.iter():
                for attr in ("src", "href", "{http://www.w3.org/1999/xlink}href"):
                    target, fragment = resolve(path, el.get(attr, "data:"))
                    if target is None:
                        continue
                    assert target in names, f"{path}: {el.get(attr)}"
                    if fragment and target.endswith(".xhtml"):
                        assert fragment in ids_of(z, target), f"{path}: {el.get(attr)}"
        if media == "application/x-dtbncx+xml":
            for content in ET.fromstring(z.read(path)).iter(tag("ncx", "content")):
                target, fragment = resolve(path, content.get("src"))
                assert target in names
                assert not fragment or fragment in ids_of(z, target), content.get("src")
        if media == "text/css" or media == XHTML:
            css = text_of(z, path)
            for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", css):
                target, _ = resolve(path, ref)
                assert target is None or target in names, f"{path}: url({ref})"


def package(
    tmp_path, pages, files=None, raw=None, cover=None, name="in.epub", cover_meta_only=False
):
    """A small EPUB: `pages` are bodies written to OEBPS/text/<key>.xhtml, `files` (path inside
    OEBPS -> bytes or str) are listed in the manifest, `raw` entries go into the zip as given.
    The `cover` file is marked by a cover-image property and a cover meta, or by the meta only."""
    files = dict(files or {})
    items = [("ncx", "toc.ncx", "application/x-dtbncx+xml", "")]
    parts = {"OEBPS/toc.ncx": '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap/></ncx>'}
    for key, body in pages.items():
        html = (
            '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{NS["h"]}"><head><title>{key}</title></head><body>{body}</body></html>'
        )
        items.append((key, f"text/{key}.xhtml", XHTML, ""))
        parts[f"OEBPS/text/{key}.xhtml"] = html
    for n, (path, data) in enumerate(files.items()):
        ident = "cover-image" if path == cover else f"f{n}"
        props = "cover-image" if path == cover and not cover_meta_only else ""
        items.append((ident, path, MEDIA[posixpath.splitext(path)[1]], props))
        parts[f"OEBPS/{path}"] = data
    manifest_xml = "".join(
        f'<item id="{i}" href="{h}" media-type="{m}"' + (f' properties="{p}"' if p else "") + "/>"
        for i, h, m, p in items
    )
    refs = "".join(f'<itemref idref="{key}"/>' for key in pages)
    cover_meta = '<meta name="cover" content="cover-image"/>' if cover else ""
    parts["OEBPS/content.opf"] = (
        f'<package xmlns="{NS["opf"]}" version="3.0" unique-identifier="u">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="u">x</dc:identifier><dc:title>T</dc:title>'
        f"<dc:language>en</dc:language>{cover_meta}</metadata>"
        f'<manifest>{manifest_xml}</manifest><spine toc="ncx">{refs}</spine></package>'
    )
    parts["META-INF/container.xml"] = (
        f'<container version="1.0" xmlns="{NS["c"]}"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    parts.update(raw or {})
    return make_epub(tmp_path / name, parts)


def test_messy_epub_x4(tmp_path, messy_epub):
    rep = optimize_epub(messy_epub, tmp_path / "o.epub", Options(device="x4"))
    z = zipfile.ZipFile(tmp_path / "o.epub")
    names = z.namelist()
    assert not any(
        n.endswith((".otf", ".ttf", ".woff", ".woff2", ".gif", ".webp", ".svg")) for n in names
    )
    assert not any(".DS_Store" in n for n in names)
    css = "".join(z.read(n).decode() for n in names if n.endswith(".css"))
    assert "float" not in css and "flex" not in css and "@font-face" not in css
    assert all(len(z.read(n)) <= 100_000 for n in names if n.endswith(".xhtml"))
    assert rep.after["images"] < rep.before["images"]


def test_drm_refused(tmp_path, drm_epub):
    with pytest.raises(DRMError, match="DRM-protected"):
        optimize_epub(drm_epub, tmp_path / "o.epub", Options())


def test_x4_messy_package_is_sound_and_reports_what_it_did(tmp_path, messy_epub):
    z, rep = run(tmp_path, messy_epub)
    check_package(z)
    assert {"svg_removed", "font_removed", "chapter_split"} <= set(kinds(rep))
    assert "image_error" not in kinds(rep)
    assert not any(n.startswith("OPS/img/unused") for n in z.namelist())


def test_x4_images_are_converted_renamed_and_every_reference_follows(tmp_path, messy_epub):
    z, _ = run(tmp_path, messy_epub)
    items = manifest(z)
    images = {p for p, i in items.items() if i.get("media-type").startswith("image/")}
    assert images == {
        "OPS/img/cover.jpg",
        "OPS/img/photo.jpg",
        "OPS/img/logo.jpg",  # RGBA PNG, not line art: baseline JPEG
        "OPS/img/anim.png",  # GIF line art: PNG
        "OPS/img/pic.jpg",  # WebP photo: JPEG
        "OPS/images/data-1.jpg",  # the data: URI, used twice, saved once
    }
    assert items["OPS/img/logo.jpg"].get("id") == "logo"
    assert items["OPS/img/logo.jpg"].get("media-type") == "image/jpeg"
    assert items["OPS/img/anim.png"].get("media-type") == "image/png"
    ch1 = text_of(z, "OPS/xhtml/ch1.xhtml")
    for ref in ("../img/logo.jpg", "../img/anim.png", "../img/pic.jpg", "../images/data-1.jpg"):
        assert f'src="{ref}"' in ch1
    assert ch1.count("../images/data-1.jpg") == 2
    assert "spacer.png" not in ch1 and "after the spacer" in ch1  # the image goes, its text stays
    assert "data:" not in ch1 and "diagram" not in ch1
    css = text_of(z, "OPS/css/style.css")
    # backgrounds go on Xteink; logo.jpg stays for its <img>
    assert "logo.jpg" not in css and "spacer.png" not in css and "height: 1em" in css
    for path in images:
        im = Image.open(BytesIO(z.read(path)))
        assert im.mode == "L" and im.width <= 480 and im.height <= 800, path
        assert not im.info.get("progressive")


def test_x4_strips_layout_css_everywhere_and_adds_the_eink_sheet(tmp_path, messy_epub):
    z, _ = run(tmp_path, messy_epub)
    ch1 = text_of(z, "OPS/xhtml/ch1.xhtml")
    assert "float" not in ch1 and "color:#222" not in ch1  # style attribute and <style>
    css = text_of(z, "OPS/css/style.css")
    assert "width: 40%" in css and "justify-content" in css and "color: #333" not in css
    assert not re.search(r"position|column|flex|float|font-face", css)
    eink = (
        "img{max-width:100%;height:auto} pre{white-space:pre-wrap} table{border-collapse:collapse}"
    )
    assert text_of(z, "OPS/eco-eink.css") == eink
    items = manifest(z)
    assert items["OPS/eco-eink.css"].get("media-type") == "text/css"
    pages = [p for p, i in items.items() if i.get("media-type") == XHTML]
    assert len(pages) >= 6  # nav, cover, ch1, ch2 and the parts of the big chapter
    for page in pages:
        links = [
            link.get("href")
            for link in ET.fromstring(z.read(page)).iterfind(".//h:link", NS)
            if link.get("href").endswith("eco-eink.css")
        ]
        assert [posixpath.normpath(posixpath.join(posixpath.dirname(page), h)) for h in links] == [
            "OPS/eco-eink.css"
        ]


def test_x4_removes_svg_and_fonts_and_keeps_the_manifest_honest(tmp_path, messy_epub):
    z, rep = run(tmp_path, messy_epub)
    items = manifest(z)
    assert not [
        p for p, i in items.items() if "svg" in i.get("media-type") or "font" in i.get("media-type")
    ]
    cover = ET.fromstring(z.read("OPS/xhtml/cover.xhtml"))
    img = cover.find(".//h:img", NS)
    assert img.get("src") == "../img/cover.jpg" and img.get("alt") == ""
    assert not set(img.attrib) - {"src", "alt"}
    assert cover.find(".//{http://www.w3.org/2000/svg}svg") is None
    for page in ("cover", "ch1"):  # no inline SVG left: the svg property must go (OPF-015)
        assert items[f"OPS/xhtml/{page}.xhtml"].get("properties") is None
    by_kind = {f.kind: f for f in rep.findings}
    assert (
        by_kind["svg_removed"].level == "warning" and "1 inline" in by_kind["svg_removed"].message
    )
    assert by_kind["font_removed"].level == "info" and "1 " in by_kind["font_removed"].message


def test_x4_splits_the_big_chapter_and_every_link_still_resolves(tmp_path, messy_epub):
    z, rep = run(tmp_path, messy_epub)
    pages = spine(z)
    parts = [p for p in pages if p.startswith("OPS/xhtml/big")]
    assert parts[0] == "OPS/xhtml/big.xhtml" and len(parts) >= 3
    assert pages == ["OPS/xhtml/cover.xhtml", "OPS/xhtml/ch1.xhtml", "OPS/xhtml/ch2.xhtml", *parts]
    assert all(len(z.read(p)) <= CHAPTER_LIMIT_BYTES for p in parts)
    found = [e.get("id") for p in parts for e in ET.fromstring(z.read(p)).iterfind(".//h:p", NS)]
    assert len(found) == 625 and len(set(found)) == 625  # nothing lost, nothing doubled
    [split] = [f for f in rep.findings if f.kind == "chapter_split"]
    assert split.level == "info" and f"into {len(parts)} files" in split.message
    ch1 = ET.fromstring(z.read("OPS/xhtml/ch1.xhtml"))
    link = next(a for a in ch1.iterfind(".//h:a", NS) if a.text == "Section 12")
    home, fragment = resolve("OPS/xhtml/ch1.xhtml", link.get("href"))
    assert fragment == "sec-12" and home != "OPS/xhtml/big.xhtml" and home in parts
    first = ET.fromstring(z.read(parts[0]))
    to_last = next(a for a in first.iterfind(".//h:a", NS) if a.text == "last section")
    assert resolve(parts[0], to_last.get("href"))[0] == parts[-1]
    last = ET.fromstring(z.read(parts[-1]))
    to_first = next(a for a in last.iterfind(".//h:a", NS) if a.text == "first section")
    assert to_first.get("href") == "big.xhtml#sec-1"
    check_package(z)  # nav and NCX targets exist, with their ids


def test_general_messy_keeps_what_the_profile_keeps(tmp_path, messy_epub):
    src = zipfile.ZipFile(messy_epub)
    z, rep = run(tmp_path, messy_epub, GENERAL)
    check_package(z)
    names = z.namelist()
    assert rep.findings == []
    assert z.read("OPS/css/style.css") == src.read("OPS/css/style.css")  # CSS untouched
    assert z.read("OPS/xhtml/big.xhtml") == src.read("OPS/xhtml/big.xhtml")  # nothing to change
    assert len(spine(z)) == 4 and "OPS/eco-eink.css" not in names
    assert "OPS/img/unused.png" not in names and "OPS/img/diagram.svg" in names
    assert Image.open(BytesIO(z.read("OPS/img/spacer.png"))).size == (10, 10)  # tiny image kept
    logo = Image.open(BytesIO(z.read("OPS/img/logo.png")))
    assert (logo.format, logo.mode) == ("PNG", "RGBA")
    assert {"OPS/img/anim.png", "OPS/img/pic.jpg", "OPS/images/data-1.png"} <= set(names)
    photo = Image.open(BytesIO(z.read("OPS/img/photo.jpg")))
    assert photo.mode == "RGB" and max(photo.size) == 1600 and not photo.info.get("progressive")
    ch1 = text_of(z, "OPS/xhtml/ch1.xhtml")
    assert "float:left" in ch1 and "svg" in ch1 and 'src="../img/spacer.png"' in ch1
    assert manifest(z)["OPS/xhtml/ch1.xhtml"].get("properties") == "svg"  # inline SVG stays
    assert manifest(z)["OPS/xhtml/cover.xhtml"].get("properties") == "svg"  # so does the cover
    assert z.read("OPS/xhtml/cover.xhtml") == src.read("OPS/xhtml/cover.xhtml")  # wrapper as is


def test_general_subsets_the_font_to_the_characters_of_the_book(tmp_path, messy_epub):
    src = zipfile.ZipFile(messy_epub)
    z, _ = run(tmp_path, messy_epub, GENERAL)
    data = z.read("OPS/fonts/serif.otf")
    assert len(data) < len(src.read("OPS/fonts/serif.otf"))
    pages = (n for n in z.namelist() if n.endswith(".xhtml"))
    used = "".join("".join(ET.fromstring(z.read(n)).itertext()) for n in pages)
    used += text_of(z, "OPS/css/style.css")
    cmap = TTFont(BytesIO(data)).getBestCmap()
    cased = used + used.upper() + used.lower()  # text-transform and small caps show the other case
    assert ord("T") in cmap and ord("?") not in cmap
    assert {chr(c) for c in cmap} == set(FONT_CHARS) & set(cased)
    assert manifest(z)["OPS/fonts/serif.otf"].get("media-type") == "font/otf"


def test_general_subset_keeps_the_case_forms_that_text_transform_shows(tmp_path):
    css = (
        "@font-face{font-family:F;src:url(../fonts/f.otf)}"
        "h1{text-transform:uppercase}p{text-transform:lowercase}"
    )
    files = {"fonts/f.otf": make_font(), "css/s.css": css}
    src = package(tmp_path, {"c": f"{LINK}<h1>Chapter one</h1><p>XYZ</p>"}, files)
    z, _ = run(tmp_path, src, GENERAL)
    chars = {chr(c) for c in TTFont(BytesIO(z.read("OEBPS/fonts/f.otf"))).getBestCmap()}
    assert set("CHAPTERONE") <= chars  # uppercase shows "CHAPTER ONE"
    assert set("xyz") <= chars  # lowercase shows "xyz"


def test_general_subset_keeps_every_opentype_feature_and_the_glyphs_it_reaches(tmp_path):
    css = "@font-face{font-family:F;src:url(../fonts/f.otf)}p{font-variant:small-caps}"
    files = {"fonts/f.otf": make_font(small_caps=True), "css/s.css": css}
    src = package(tmp_path, {"c": f"{LINK}<p>abc</p>"}, files)
    z, _ = run(tmp_path, src, GENERAL)
    out = TTFont(BytesIO(z.read("OEBPS/fonts/f.otf")))
    features = {r.FeatureTag for r in out["GSUB"].table.FeatureList.FeatureRecord}
    assert "smcp" in features  # fontTools keeps only a short list of features unless told to
    assert {"u0061.sc", "u0062.sc", "u0063.sc"} <= set(out.getGlyphOrder())


def test_general_keeps_the_font_flavor(tmp_path):
    font = make_font(flavor="woff")
    css = "@font-face{font-family:F;src:url(../fonts/f.woff)}"
    src = package(tmp_path, {"c": f"{LINK}<p>Hello</p>"}, {"fonts/f.woff": font, "css/s.css": css})
    z, rep = run(tmp_path, src, GENERAL)
    out = z.read("OEBPS/fonts/f.woff")
    assert out[:4] == b"wOFF" and len(out) < len(font) and rep.findings == []
    assert TTFont(BytesIO(out)).flavor == "woff"


def test_a_font_that_cannot_be_subset_is_kept_with_a_finding(tmp_path):
    broken = b"wOF2" + bytes(300)  # WOFF2 needs brotli, which is not installed; junk fails anyway
    css = "@font-face{font-family:F;src:url(../fonts/f.woff2)}"
    src = package(tmp_path, {"c": f"{LINK}<p>Hi</p>"}, {"fonts/f.woff2": broken, "css/s.css": css})
    z, rep = run(tmp_path, src, GENERAL)
    assert z.read("OEBPS/fonts/f.woff2") == broken
    assert [(f.kind, f.level) for f in rep.findings] == [("font_kept", "info")]
    assert "f.woff2" in rep.findings[0].message


OBFUSCATION = "http://www.idpf.org/2008/embedding"


def encryption(*uris, algorithm=OBFUSCATION):
    entries = "".join(
        f'<enc:EncryptedData><enc:EncryptionMethod Algorithm="{algorithm}"/><enc:CipherData>'
        f'<enc:CipherReference URI="{uri}"/></enc:CipherData></enc:EncryptedData>'
        for uri in uris
    )
    return (
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        f'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">{entries}</encryption>'
    )


def obfuscated_font(tmp_path, algorithm=OBFUSCATION):
    css = "@font-face{font-family:F;src:url(../fonts/f.otf)}"
    return package(
        tmp_path,
        {"c": f"{LINK}<p>Hi</p>"},
        {"fonts/f.otf": make_font(), "css/s.css": css},
        raw={"META-INF/encryption.xml": encryption("OEBPS/fonts/f.otf", algorithm=algorithm)},
    )


def test_obfuscated_font_is_kept_as_is_on_general(tmp_path):
    src = obfuscated_font(tmp_path)
    z, rep = run(tmp_path, src, GENERAL)
    assert z.read("OEBPS/fonts/f.otf") == zipfile.ZipFile(src).read("OEBPS/fonts/f.otf")
    assert "OEBPS/fonts/f.otf" in text_of(z, "META-INF/encryption.xml")
    assert [(f.kind, f.level) for f in rep.findings] == [("font_kept", "info")]


@pytest.mark.parametrize("algorithm", [OBFUSCATION, "http://ns.adobe.com/pdf/enc#RC"])
def test_xteink_drops_fonts_and_their_encryption_entries(tmp_path, algorithm):
    z, rep = run(tmp_path, obfuscated_font(tmp_path, algorithm))
    assert "OEBPS/fonts/f.otf" not in z.namelist()
    assert "META-INF/encryption.xml" not in z.namelist()  # no entry left
    assert "@font-face" not in text_of(z, "OEBPS/css/s.css")
    assert kinds(rep) == ["font_removed"]
    check_package(z)


def test_encryption_entries_of_dropped_files_go_and_the_others_stay(tmp_path):
    files = {
        "fonts/gone.otf": make_font(),  # not used anywhere: dropped
        "fonts/keep.otf": make_font(),
        "css/s.css": "@font-face{font-family:K;src:url(../fonts/keep.otf)}",
    }
    uris = ("OEBPS/fonts/gone.otf", "OEBPS/fonts/keep.otf")
    raw = {"META-INF/encryption.xml": encryption(*uris)}
    z, _ = run(tmp_path, package(tmp_path, {"c": f"{LINK}<p>Hi</p>"}, files, raw=raw), GENERAL)
    assert "OEBPS/fonts/gone.otf" not in z.namelist()
    remaining = text_of(z, "META-INF/encryption.xml")
    assert "fonts/keep.otf" in remaining and "fonts/gone.otf" not in remaining


@pytest.mark.parametrize("algorithm", ["http://www.w3.org/2001/04/xmlenc#aes128-cbc", "urn:other"])
def test_encrypted_content_is_refused(tmp_path, algorithm):
    entry = encryption("OEBPS/text/c.xhtml", algorithm=algorithm)
    src = package(tmp_path, {"c": "<p>Hi</p>"}, raw={"META-INF/encryption.xml": entry})
    with pytest.raises(DRMError, match=r"EPUB is DRM-protected: in\.epub"):
        optimize_epub(src, tmp_path / "o.epub", GENERAL)
    assert not (tmp_path / "o.epub").exists()


def test_rights_file_is_refused_with_the_file_name(tmp_path, drm_epub):
    with pytest.raises(DRMError, match=r"EPUB is DRM-protected: drm\.epub"):
        optimize_epub(drm_epub, tmp_path / "o.epub", X4)


def corrupt_image_book(tmp_path):
    bad = image_bytes((300, 300), "JPEG")
    bad = bad[: len(bad) // 2]  # truncated: Pillow raises OSError when it decodes
    body = (
        '<link rel="stylesheet" href="../css/s.css"/>'
        '<p><img src="../img/bad.jpg" alt="b"/> kept text <img src="../img/ok.png" alt="o"/></p>'
    )
    files = {
        "img/bad.jpg": bad,
        "img/ok.png": image_bytes((100, 100), "PNG"),
        "css/s.css": ".b{background:url(../img/bad.jpg)} .k{text-align:left}",
    }
    return package(tmp_path, {"c": body}, files), bad


def test_corrupt_image_is_removed_with_its_references_on_xteink(tmp_path):
    src, _ = corrupt_image_book(tmp_path)
    z, rep = run(tmp_path, src, X4)
    check_package(z)
    assert "OEBPS/img/bad.jpg" not in z.namelist() and "OEBPS/img/bad.jpg" not in manifest(z)
    page = text_of(z, "OEBPS/text/c.xhtml")
    assert "bad.jpg" not in page and "kept text" in page and "ok." in page  # the other image stays
    css = text_of(z, "OEBPS/css/s.css")
    assert "bad.jpg" not in css and ".k{text-align:left}" in css
    [finding] = [f for f in rep.findings if f.kind == "image_error"]
    assert finding.level == "warning" and "bad.jpg" in finding.message


def test_corrupt_image_is_kept_unchanged_on_general(tmp_path):
    src, bad = corrupt_image_book(tmp_path)
    z, rep = run(tmp_path, src, GENERAL)
    check_package(z)
    assert z.read("OEBPS/img/bad.jpg") == bad
    assert 'src="../img/bad.jpg"' in text_of(z, "OEBPS/text/c.xhtml")
    assert "url(../img/bad.jpg)" in text_of(z, "OEBPS/css/s.css")
    assert [(f.kind, f.level) for f in rep.findings] == [("image_error", "warning")]


def test_decompression_bomb_is_a_finding_not_a_crash(tmp_path, monkeypatch):
    src = package(
        tmp_path,
        {"c": '<img src="../img/a.png" alt=""/>'},
        {"img/a.png": image_bytes((100, 100), "PNG")},
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # a 100x100 image is now a bomb
    z, rep = run(tmp_path, src, X4)
    assert "OEBPS/img/a.png" not in z.namelist() and kinds(rep) == ["image_error"]
    check_package(z)


def test_stock_firmware_warns_that_images_are_kept(tmp_path):
    body = '<p><img src="../img/a.png" alt=""/></p>'
    src = package(tmp_path, {"c": body}, {"img/a.png": image_bytes((100, 100), "PNG")})
    for options in (X4, Options(device="x4", firmware="crosspoint"), GENERAL):
        assert "stock_images" not in kinds(run(tmp_path, src, options)[1])
    z, rep = run(tmp_path, src, Options(device="x4", firmware="stock"))
    [warning] = [f for f in rep.findings if f.kind == "stock_images"]
    assert warning.level == "warning" and "stock firmware" in warning.message
    assert any(i.get("media-type").startswith("image/") for i in manifest(z).values())
    z, rep = run(tmp_path, src, Options(device="general", firmware="stock"))
    assert "stock_images" not in kinds(rep)
    plain = package(tmp_path, {"c": "<p>no pictures</p>"}, name="plain.epub")
    assert kinds(run(tmp_path, plain, Options(device="x4", firmware="stock"))[1]) == []


def cover_book(tmp_path, cover_meta_only=False):
    body = '<p><img src="../img/a.png" alt=""/><img src="../img/b.png" alt=""/></p>'
    files = {
        name: image_bytes((300, 400), "PNG", seed=n)
        for n, name in enumerate(("img/cover.png", "img/a.png", "img/b.png"), 1)
    }
    return package(
        tmp_path, {"c": body}, files, cover="img/cover.png", cover_meta_only=cover_meta_only
    )


@pytest.mark.parametrize("meta_only", [False, True])
def test_small_stock_drops_images_but_never_the_cover(tmp_path, meta_only):
    src = cover_book(tmp_path, meta_only)
    z, rep = run(tmp_path, src, Options(device="x4", size="small", firmware="stock"))
    check_package(z)
    images = [p for p, i in manifest(z).items() if i.get("media-type").startswith("image/")]
    assert images == ["OEBPS/img/cover.jpg"]  # converted like any image: noise becomes JPEG
    assert "<img" not in text_of(z, "OEBPS/text/c.xhtml")
    [dropped] = [f for f in rep.findings if f.kind == "images_dropped"]
    assert dropped.level == "info" and "2 " in dropped.message
    assert "stock_images" in kinds(rep)  # the cover is still an image
    _, opf = opf_of(z)
    assert opf.find(".//opf:meta[@name='cover']", NS).get("content") == "cover-image"


def test_xteink_split_repeats_a_single_wrapper_and_relinks_nav_and_ncx(tmp_path):
    paragraphs = "".join(f'<p id="p{n}">{n} {"x" * 600}</p>' for n in range(300))
    wrapper = f'<section class="chapter" id="c"><h1 id="h">Title</h1>{paragraphs}</section>'
    nav = (
        '<p><a href="ch.xhtml#p250">late</a> <a href="ch.xhtml#h">top</a> '
        '<a href="ch.xhtml">file</a></p>'
    )
    ncx = (
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
        '<navPoint id="a" playOrder="1"><navLabel><text>Late</text></navLabel>'
        '<content src="text/ch.xhtml#p250"/></navPoint></navMap></ncx>'
    )
    src = package(tmp_path, {"ch": wrapper, "nav": nav}, raw={"OEBPS/toc.ncx": ncx})
    z, rep = run(tmp_path, src, X4)
    check_package(z)
    pages = spine(z)
    parts = [p for p in pages if p.startswith("OEBPS/text/ch")]
    assert parts[:2] == ["OEBPS/text/ch.xhtml", "OEBPS/text/ch-2.xhtml"] and len(parts) >= 2
    assert pages == [*parts, "OEBPS/text/nav.xhtml"]
    seen = []
    for number, part in enumerate(parts):
        data = z.read(part)
        assert len(data) <= CHAPTER_LIMIT_BYTES
        body = ET.fromstring(data).find("h:body", NS)
        [section] = list(body)
        assert section.tag == tag("h", "section") and section.get("class") == "chapter"
        assert (section.get("id") == "c") == (number == 0)  # the id is not repeated
        assert (section.find("h:h1", NS) is not None) == (number == 0)
        seen += [p.get("id") for p in section.iterfind("h:p", NS)]
    assert seen == [f"p{n}" for n in range(300)]
    links = ET.fromstring(z.read("OEBPS/text/nav.xhtml")).findall(".//h:a", NS)
    late, top, whole = (a.get("href") for a in links)
    assert late.startswith("ch-") and late.endswith("#p250")
    assert (top, whole) == ("ch.xhtml#h", "ch.xhtml")
    point = ET.fromstring(z.read("OEBPS/toc.ncx")).find(".//ncx:content", NS)
    assert point.get("src") == f"text/{late}"
    assert [f.kind for f in rep.findings] == ["chapter_split"]


def test_a_link_to_an_id_that_every_part_repeats_goes_to_the_first_part(tmp_path):
    paragraphs = "".join(f"<p>{n} {'x' * 600}</p>" for n in range(300))
    page = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="{NS["h"]}"><head><title>ch</title></head>'
        f'<body id="top">{paragraphs}</body></html>'
    )
    nav = '<p><a href="ch.xhtml#top">top</a></p>'
    src = package(tmp_path, {"ch": "", "nav": nav}, raw={"OEBPS/text/ch.xhtml": page})
    z, _ = run(tmp_path, src, X4)
    check_package(z)
    assert len(spine(z)) > 2
    [link] = ET.fromstring(z.read("OEBPS/text/nav.xhtml")).findall(".//h:a", NS)
    assert link.get("href") == "ch.xhtml#top"


def test_xteink_single_element_over_the_limit_stays_whole_with_a_warning(tmp_path):
    body = f"<p>short</p><table><tr><td>{'x' * 150_000}</td></tr></table><p>end</p>"
    z, rep = run(tmp_path, package(tmp_path, {"c": body}), X4)
    parts = spine(z)
    assert len(parts) == 3
    assert [len(z.read(p)) > CHAPTER_LIMIT_BYTES for p in parts] == [False, True, False]
    assert "x" * 150_000 in z.read(parts[1]).decode()
    [finding] = [f for f in rep.findings if f.kind == "chapter_split"]
    assert finding.level == "warning" and "over the limit" in finding.message
    check_package(z)


def test_xteink_small_chapters_and_general_big_ones_are_not_split(tmp_path):
    body = "".join(f"<p>{n} {'x' * 500}</p>" for n in range(400))
    src = package(tmp_path, {"c": body})
    z, rep = run(tmp_path, src, GENERAL)
    assert spine(z) == ["OEBPS/text/c.xhtml"] and "chapter_split" not in kinds(rep)
    z, rep = run(tmp_path, package(tmp_path, {"c": "<p>small</p>"}, name="s.epub"), X4)
    assert spine(z) == ["OEBPS/text/c.xhtml"] and "chapter_split" not in kinds(rep)


def test_images_that_change_extension_get_a_free_name_in_their_own_folder(tmp_path):
    files = {
        "img/x.png": image_bytes((100, 100), "PNG", seed=1),  # noise: becomes x.jpg on Xteink
        "img/x.jpg": image_bytes((100, 100), "JPEG", seed=2),  # takes that name already
        "img/sub/x.png": image_bytes((100, 100), "PNG", seed=3),
    }
    body = (
        '<link rel="stylesheet" href="../css/s.css"/>'
        '<p><img src="../img/x.png" alt=""/><img src="../img/x.jpg" alt=""/>'
        '<img src="../img/sub/x.png" alt=""/></p>'
    )
    src = package(
        tmp_path, {"c": body}, {**files, "css/s.css": "a{list-style-image:url('../img/x.png')}"}
    )
    z, _ = run(tmp_path, src, X4)
    check_package(z)
    images = sorted(p for p in z.namelist() if p.startswith("OEBPS/img/"))
    assert images == ["OEBPS/img/sub/x.jpg", "OEBPS/img/x-1.jpg", "OEBPS/img/x.jpg"]
    page = text_of(z, "OEBPS/text/c.xhtml")
    assert (
        page.index("../img/x-1.jpg") < page.index("../img/x.jpg") < page.index("../img/sub/x.jpg")
    )
    assert "url('../img/x-1.jpg')" in text_of(z, "OEBPS/css/s.css")
    assert manifest(z)["OEBPS/img/x-1.jpg"].get("media-type") == "image/jpeg"


def test_data_uris_in_pages_and_css_become_files_on_both_profiles(tmp_path):
    png = image_bytes((200, 200), "PNG", seed=5)  # many colours: a photo, not line art
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    gif = base64.b64encode(image_bytes((150, 150), "GIF", seed=6)).decode()
    other = f"data:image/gif;base64,{gif}"
    font = "data:font/woff2;base64,AAAA"  # not an image: left alone
    css = f'.a{{list-style-image:url("{uri}")}} .b{{list-style-image:url({other})}}'
    body = (
        f'{LINK}<p style="list-style-image:url({uri})"><img src="{uri}" alt=""/>'
        f'<a href="{font}">f</a></p>'
    )
    src = package(tmp_path, {"c": body}, {"css/s.css": css})
    for options, ext, gif_ext in ((GENERAL, "png", "png"), (X4, "jpg", "jpg")):
        z, _ = run(tmp_path, src, options)
        check_package(z)
        data = sorted(p for p in z.namelist() if p.startswith("OEBPS/images/"))
        assert data == [f"OEBPS/images/data-1.{ext}", f"OEBPS/images/data-2.{gif_ext}"]
        page, sheet = text_of(z, "OEBPS/text/c.xhtml"), text_of(z, "OEBPS/css/s.css")
        assert page.count(f"../images/data-1.{ext}") == 2 and f"../images/data-1.{ext}" in sheet
        assert f"url(../images/data-2.{gif_ext})" in sheet and font in page
        assert "data:image" not in page + sheet
        item = manifest(z)[f"OEBPS/images/data-1.{ext}"]
        assert item.get("id") == "data-1" and item.get("media-type") == MEDIA[f".{ext}"]


def test_a_broken_data_uri_is_left_alone(tmp_path):
    body = '<p><img src="data:image/png;base64,@@@@" alt=""/></p>'
    z, _ = run(tmp_path, package(tmp_path, {"c": body}), GENERAL)
    assert "base64,@@@@" in text_of(z, "OEBPS/text/c.xhtml")
    assert not [p for p in z.namelist() if "/images/" in p]


def test_svg_wrapper_with_a_title_is_unwrapped_on_xteink_and_kept_on_general(tmp_path):
    svg = "http://www.w3.org/2000/svg"
    wrapper = (
        f'<svg xmlns="{svg}" xmlns:xlink="http://www.w3.org/1999/xlink" width="100%" height="100%">'
        '<title>Cover</title><image xlink:href="../img/a.png" width="10" height="10"/></svg>'
    )
    drawing = f'<svg xmlns="{svg}"><circle r="3"/><circle r="4"/></svg>'
    src = package(
        tmp_path,
        {"c": f"<div>{wrapper}</div><p>between</p>{drawing}"},
        {"img/a.png": image_bytes((80, 80), "PNG")},
    )
    z, rep = run(tmp_path, src, X4)
    root = ET.fromstring(z.read("OEBPS/text/c.xhtml"))
    img = root.find(".//h:div/h:img", NS)
    assert img is not None and set(img.attrib) == {"src", "alt"} and img.get("alt") == ""
    assert root.find(".//h:p", NS).text == "between"
    assert root.findall(f".//{{{svg}}}svg") == [] and "svg_removed" in kinds(rep)
    z, rep = run(tmp_path, src, GENERAL)
    root = ET.fromstring(z.read("OEBPS/text/c.xhtml"))
    assert root.find(".//h:img", NS) is None  # the wrapper keeps its own fit to the page
    assert len(root.findall(f".//{{{svg}}}svg")) == 2 and "svg_removed" not in kinds(rep)


def test_svg_files_are_removed_on_xteink_with_every_reference(tmp_path):
    drawing = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'
    body = (
        '<link rel="stylesheet" href="../css/s.css"/><p><img src="../img/d.svg" alt="d"/>after</p>'
    )
    css = ".d{list-style-image:url(../img/d.svg);text-align:left}"
    src = package(tmp_path, {"c": body}, {"img/d.svg": drawing, "css/s.css": css})
    z, rep = run(tmp_path, src, X4)
    check_package(z)
    assert "OEBPS/img/d.svg" not in z.namelist()
    assert "d.svg" not in text_of(z, "OEBPS/text/c.xhtml") + text_of(z, "OEBPS/css/s.css")
    assert "after" in text_of(z, "OEBPS/text/c.xhtml") and "text-align:left" in text_of(
        z, "OEBPS/css/s.css"
    )
    [finding] = [f for f in rep.findings if f.kind == "svg_removed"]
    assert "1 SVG file" in finding.message
    z, rep = run(tmp_path, src, GENERAL)
    assert z.read("OEBPS/img/d.svg") == drawing.encode() and "svg_removed" not in kinds(rep)


def test_unreferenced_items_are_dropped_and_anything_in_doubt_is_kept(tmp_path):
    files = {
        "img/page.png": image_bytes((50, 50), "PNG", seed=1),
        "img/drop-me.png": image_bytes((50, 50), "PNG", seed=2),
        "img/css-only.png": image_bytes((50, 50), "PNG", seed=3),
        "img/cover.png": image_bytes((50, 50), "PNG", seed=4),
        "css/s.css": "p{background:url(../img/css-only.png)}",
        "css/drop-me.css": "p{color:red}",
        "fonts/drop-me.otf": make_font(),
        "text/orphan.xhtml": "<html xmlns='http://www.w3.org/1999/xhtml'><body/></html>",
    }
    body = '<link rel="stylesheet" href="../css/s.css"/><p><img src="../img/page.png" alt=""/></p>'
    src = package(tmp_path, {"c": body}, files, cover="img/cover.png")
    z, _ = run(tmp_path, src, GENERAL)
    check_package(z)
    assert set(manifest(z)) == {
        "OEBPS/toc.ncx",
        "OEBPS/text/c.xhtml",
        "OEBPS/img/page.png",
        "OEBPS/img/css-only.png",  # referenced from a stylesheet
        "OEBPS/img/cover.png",  # the cover needs no page
        "OEBPS/css/s.css",
    }
    assert not [n for n in z.namelist() if "drop-me" in n or "orphan" in n]


def test_items_of_other_kinds_are_never_dropped(tmp_path):
    files = {"audio/a.smil": '<smil xmlns="http://www.w3.org/ns/SMIL"/>'}
    z, _ = run(tmp_path, package(tmp_path, {"c": "<p>x</p>"}, files), GENERAL)
    assert "OEBPS/audio/a.smil" in manifest(z)


def test_unsafe_zip_entries_and_os_junk_are_not_copied(tmp_path):
    raw = {n: b"x" for n in ("../evil.txt", "/abs.txt", "OEBPS/../../up.txt", "OEBPS/.DS_Store")}
    raw["__MACOSX/OEBPS/._c.xhtml"] = b"x"
    z, rep = run(tmp_path, package(tmp_path, {"c": "<p>x</p>"}, raw=raw), GENERAL)
    assert not [n for n in z.namelist() if ".." in n or n.startswith("/") or "DS_Store" in n]
    assert "__MACOSX/OEBPS/._c.xhtml" not in z.namelist()
    [finding] = [f for f in rep.findings if f.kind == "unsafe_path"]
    assert finding.level == "warning" and "3" in finding.message


def test_a_zip_entry_with_a_drive_is_not_copied(tmp_path):
    raw = {"C:/evil.txt": b"x", "D:evil.txt": b"x"}
    z, rep = run(tmp_path, package(tmp_path, {"c": "<p>x</p>"}, raw=raw), GENERAL)
    assert not [n for n in z.namelist() if "evil" in n]
    [finding] = [f for f in rep.findings if f.kind == "unsafe_path"]
    assert "2 zip entries" in finding.message


@pytest.mark.parametrize(
    "name, unsafe",
    [
        ("OEBPS/text/c.xhtml", False),
        ("/abs.txt", True),
        ("OEBPS/../../up.txt", True),
        ("C:/evil.txt", True),
        ("C:evil.txt", True),
        # Python reads a backslash as "/" on Windows only; elsewhere it reaches the name
        ("OEBPS\\evil.txt", True),
        ("\\\\host\\share\\evil.txt", True),
    ],
)
def test_which_zip_entry_names_are_unsafe(name, unsafe):
    assert _unsafe_name(name) is unsafe


@pytest.mark.parametrize("cap", ["_MAX_ENTRY", "_MAX_TOTAL"])
def test_an_epub_that_unpacks_past_the_size_cap_is_refused(tmp_path, monkeypatch, cap):
    src = package(tmp_path, {"c": "<p>x</p>"}, raw={"OEBPS/big.txt": b"x" * 5000})
    monkeypatch.setattr(f"eco.epub.optimizer.{cap}", 4000)
    with pytest.raises(ValueError, match="Not a readable EPUB: in.epub.*unpacks to more than"):
        optimize_epub(src, tmp_path / "o.epub", GENERAL)
    assert not (tmp_path / "o.epub").exists()


def test_named_entities_become_characters_and_bad_xml_is_left_unchanged(tmp_path):
    pages = {"ok": "<p>a&nbsp;b &eacute; &amp; &lt; &copy;</p>", "broken": "<p>unclosed"}
    src = package(tmp_path, pages)
    for options in (GENERAL, X4):
        z, rep = run(tmp_path, src, options)
        paragraph = ET.fromstring(z.read("OEBPS/text/ok.xhtml")).find(".//h:p", NS)
        assert "".join(paragraph.itertext()) == "a b é & < ©"
        assert z.read("OEBPS/text/broken.xhtml") == zipfile.ZipFile(src).read(
            "OEBPS/text/broken.xhtml"
        )
        [finding] = [f for f in rep.findings if f.kind == "bad_xml"]
        assert finding.level == "warning" and "broken.xhtml" in finding.message
        assert z.read("OEBPS/text/ok.xhtml").startswith(b'<?xml version="1.0" encoding="utf-8"?>\n')


def test_an_image_that_a_document_left_unparsed_refers_to_keeps_its_name_and_bytes(tmp_path):
    photo = image_bytes((200, 100), "PNG", mode="RGBA", seed=4)  # X4 makes it a JPEG
    pages = {
        "ok": '<p><img src="../img/shared.png" alt="a"/><img src="../img/own.png" alt="b"/></p>',
        "broken": '<p>unclosed <img src="../img/shared.png" alt="a"/>',
    }
    files = {"img/shared.png": photo, "img/own.png": photo}
    z, rep = run(tmp_path, package(tmp_path, pages, files), X4)
    assert z.read("OEBPS/img/shared.png") == photo
    assert "OEBPS/img/own.jpg" in z.namelist() and "OEBPS/img/own.png" not in z.namelist()
    assert 'src="../img/shared.png"' in text_of(z, "OEBPS/text/ok.xhtml")
    [bad] = [f.message for f in rep.findings if f.kind == "bad_xml"]
    assert "its links are not updated" in bad
    [kept] = [f for f in rep.findings if f.kind == "image_kept"]
    assert kept.level == "warning" and "OEBPS/img/shared.png" in kept.message


def test_an_unparsed_page_refers_to_an_image_in_an_unquoted_url_or_before_a_fragment(tmp_path):
    photo = image_bytes((200, 100), "PNG", mode="RGBA", seed=4)  # X4 makes it a JPEG
    broken = (
        '<p style="background: url(../img/a.png)">unclosed '
        '<img src="../img/b.png#part" alt="b"/><img src="../img/c.png?v=2" alt="c"/>'
    )
    pages = {"broken": broken}
    files = {"img/a.png": photo, "img/b.png": photo, "img/c.png": photo}
    z, rep = run(tmp_path, package(tmp_path, pages, files), X4)
    for name in ("a", "b", "c"):
        assert z.read(f"OEBPS/img/{name}.png") == photo
    assert len([f for f in rep.findings if f.kind == "image_kept"]) == 3


def test_an_image_whose_name_is_only_part_of_a_name_in_an_unparsed_page_is_converted(tmp_path):
    photo = image_bytes((200, 100), "PNG", mode="RGBA", seed=4)  # X4 makes it a JPEG
    pages = {
        "ok": '<p><img src="../img/1.png" alt="a"/><img src="../img/img-071.png" alt="b"/></p>',
        "broken": '<p>unclosed <img src="../img/img-071.png" alt="b"/>',
    }
    files = {"img/1.png": photo, "img/img-071.png": photo}
    z, rep = run(tmp_path, package(tmp_path, pages, files), X4)
    assert "OEBPS/img/1.jpg" in z.namelist()  # "1.png" is inside "img-071.png", no reference
    assert z.read("OEBPS/img/img-071.png") == photo
    assert [f.message for f in rep.findings if f.kind == "image_kept"] == [
        "OEBPS/img/img-071.png is left unchanged: a page that is not well-formed refers to it"
    ]


def test_the_doctype_and_the_xml_declaration_are_kept_or_normalised(tmp_path):
    xhtml11 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
        '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
        f'<html xmlns="{NS["h"]}"><head><title>T</title></head>'
        "<body><p>Caf&eacute;</p></body></html>"
    )
    src = package(tmp_path, {"c": ""}, raw={"OEBPS/text/c.xhtml": xhtml11})
    z, _ = run(tmp_path, src, X4)
    text = text_of(z, "OEBPS/text/c.xhtml")
    assert text.startswith('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html PUBLIC "-//W3C')
    assert 'xmlns="http://www.w3.org/1999/xhtml"' in text and "<ns0:" not in text
    assert "Café" in ET.fromstring(z.read("OEBPS/text/c.xhtml")).findtext(".//h:p", namespaces=NS)


def test_prefixes_and_the_default_namespace_survive_the_rewrite(tmp_path):
    page = (
        '<?xml version="1.0"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="{NS["h"]}" xmlns:epub="http://www.idpf.org/2007/ops" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="en" lang="en">'
        "<head><title>T</title></head>"
        '<body><p epub:type="footnote" xml:lang="fr">a</p>'
        '<svg xmlns="http://www.w3.org/2000/svg"><use xlink:href="#a"/><circle id="a" r="1"/></svg>'
        '<img src="../img/a.gif" alt=""/></body></html>'
    )
    gif = image_bytes((60, 60), "GIF")
    src = package(tmp_path, {"c": ""}, {"img/a.gif": gif}, raw={"OEBPS/text/c.xhtml": page})
    z, _ = run(tmp_path, src, GENERAL)
    text = text_of(z, "OEBPS/text/c.xhtml")
    assert "<html " in text and "<p " in text and "<body>" in text  # no prefix on XHTML elements
    assert 'epub:type="footnote"' in text and 'xml:lang="fr"' in text and "xlink:href" in text
    root = ET.fromstring(z.read("OEBPS/text/c.xhtml"))
    assert (
        root.get("lang") == "en" and root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"
    )
    assert root.find(".//h:p", NS).get("{http://www.idpf.org/2007/ops}type") == "footnote"
    assert root.find(".//{http://www.w3.org/2000/svg}use") is not None


def test_epub2_package_keeps_its_default_namespace_and_prefixed_attributes(tmp_path):
    opf = (
        '<?xml version="1.0"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf"><dc:identifier id="id">x</dc:identifier>'
        '<dc:title>T</dc:title><dc:creator opf:role="aut" opf:file-as="Doe, J">J Doe</dc:creator>'
        "<dc:language>en</dc:language></metadata><manifest>"
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="c" href="text/c.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="g" href="img/a.gif" media-type="image/gif"/></manifest>'
        '<spine toc="ncx"><itemref idref="c"/></spine>'
        '<guide><reference type="text" title="Text" href="text/c.xhtml"/>'
        '<reference type="other" title="Gone" href="img/gone.png"/></guide></package>'
    )
    gif = image_bytes((60, 60), "GIF")
    body = '<p><img src="../img/a.gif" alt=""/></p>'
    src = package(tmp_path, {"c": body}, {"img/a.gif": gif}, raw={"OEBPS/content.opf": opf})
    z, _ = run(tmp_path, src, GENERAL)
    check_package(z)
    text = text_of(z, "OEBPS/content.opf")
    assert text.count("<package ") == 1 and "<manifest>" in text and "<opf:" not in text
    dc, opf_ns = "http://purl.org/dc/elements/1.1/", "http://www.idpf.org/2007/opf"
    creator = ET.fromstring(z.read("OEBPS/content.opf")).find(f".//{{{dc}}}creator")
    assert (
        creator.get(f"{{{opf_ns}}}role") == "aut"
        and creator.get(f"{{{opf_ns}}}file-as") == "Doe, J"
    )
    assert 'opf:role="aut"' in text and "dc:creator" in text
    assert manifest(z)["OEBPS/img/a.png"].get("id") == "g"  # GIF became a PNG
    refs = [
        r.get("href")
        for r in ET.fromstring(z.read("OEBPS/content.opf")).iterfind(".//opf:reference", NS)
    ]
    assert refs == ["text/c.xhtml"]  # the guide entry for a missing file is dropped


def test_xteink_reports_an_image_under_20_px_it_removes_and_keeps_its_alt_text(tmp_path):
    files = {"icon.png": image_bytes((16, 16), "PNG"), "photo.png": image_bytes((200, 120), "PNG")}
    body = (
        '<p>Press <img src="../icon.png" alt="the power key"/> to start.</p>'
        '<p><img src="../photo.png" alt="A photo"/></p><p><img src="../icon.png" alt=""/>Again.</p>'
    )
    z, rep = run(tmp_path, package(tmp_path, {"c": body}, files), X4)
    paragraphs = ET.fromstring(z.read("OEBPS/text/c.xhtml")).findall(".//h:p", NS)
    assert ["".join(p.itertext()) for p in paragraphs] == [
        "Press the power key to start.",
        "",
        "Again.",
    ]
    assert paragraphs[1].find("h:img", NS).get("alt") == "A photo"
    small = [f for f in rep.findings if f.kind == "image_too_small"]
    assert [f.level for f in small] == ["info"] and small[0].message.startswith(
        "1 image under 20 px"
    )
    assert "OEBPS/icon.png" not in z.namelist()


def test_nothing_in_the_package_points_at_what_xteink_removed(tmp_path):
    opf = (
        f'<package xmlns="{NS["opf"]}" version="3.0" unique-identifier="u"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="u">x</dc:identifier>'
        '<dc:title>T</dc:title><dc:language>en</dc:language><meta name="cover" content="cov"/>'
        '</metadata><manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="c" href="text/c.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="alt" href="text/alt.xhtml" media-type="application/xhtml+xml" fallback="art"/>'
        '<item id="art" href="art.svg" media-type="image/svg+xml"/>'
        '<item id="cov" href="tiny.png" media-type="image/png"/></manifest>'
        '<spine toc="ncx"><itemref idref="c"/><itemref idref="alt"/>'
        '<itemref idref="art" linear="no"/></spine>'
        '<guide><reference type="cover" title="Cover" href="tiny.png"/>'
        '<reference type="text" title="Text" href="text/c.xhtml#top"/></guide></package>'
    )
    drawing = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'
    files = {"art.svg": drawing, "tiny.png": image_bytes((10, 10), "PNG")}
    pages = {"c": '<p id="top"><a href="../art.svg">the drawing</a></p>', "alt": "<p>alt</p>"}
    src = package(tmp_path, pages, files, raw={"OEBPS/content.opf": opf})
    z, _ = run(tmp_path, src, X4)
    check_package(z)
    _, root = opf_of(z)
    assert [r.get("idref") for r in root.iterfind(".//opf:itemref", NS)] == ["c", "alt"]
    assert root.find(".//opf:meta[@name='cover']", NS) is None  # the tiny cover is gone
    assert root.find(".//opf:item[@fallback]", NS) is None
    assert [r.get("type") for r in root.iterfind(".//opf:reference", NS)] == ["text"]
    link = ET.fromstring(z.read("OEBPS/text/c.xhtml")).find(".//h:a", NS)
    assert link.get("href") is None and link.text == "the drawing"  # the text stays


def test_a_style_attribute_that_filters_to_nothing_is_dropped(tmp_path):
    src = package(tmp_path, {"c": '<p style="float:left; position:absolute">x</p>'})
    z, _ = run(tmp_path, src, X4)
    assert ET.fromstring(z.read("OEBPS/text/c.xhtml")).find(".//h:p", NS).attrib == {}


def test_jpeg_extension_is_not_renamed_to_jpg(tmp_path):
    jpeg = image_bytes((100, 100), "JPEG", quality=30)  # baseline and small: kept as it is
    src = package(
        tmp_path, {"c": '<img src="../img/a.jpeg" alt=""/>'}, {"img/a.jpeg": jpeg}, name="j.epub"
    )
    for options in (GENERAL, X4):
        z, _ = run(tmp_path, src, options)
        assert "OEBPS/img/a.jpeg" in manifest(z)
        assert 'src="../img/a.jpeg"' in text_of(z, "OEBPS/text/c.xhtml")


def test_nested_wrappers_are_all_repeated_in_every_part(tmp_path):
    paragraphs = "".join(f'<p id="p{n}">{n} {"x" * 600}</p>' for n in range(300))
    body = f'<div class="outer" id="o"><section id="s">{paragraphs}</section></div>'
    z, _ = run(tmp_path, package(tmp_path, {"c": body}), X4)
    parts = spine(z)
    assert len(parts) >= 2
    seen = []
    for number, part in enumerate(parts):
        [outer] = list(ET.fromstring(z.read(part)).find("h:body", NS))
        [section] = list(outer)
        assert (outer.tag, section.tag) == (tag("h", "div"), tag("h", "section"))
        assert outer.get("class") == "outer"
        assert (outer.get("id"), section.get("id")) == (("o", "s") if number == 0 else (None, None))
        seen += [p.get("id") for p in section]
    assert seen == [f"p{n}" for n in range(300)]


def test_package_file_at_the_zip_root_and_names_with_spaces_and_accents(tmp_path):
    name = "my pic ü.png"
    page = (
        f'<html xmlns="{NS["h"]}"><head><title>T</title></head><body>'
        f'<p><img src="img/{quote(name)}" alt=""/></p></body></html>'
    )
    opf = (
        f'<package xmlns="{NS["opf"]}" version="3.0" unique-identifier="u"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="u">x</dc:identifier>'
        "<dc:title>T</dc:title><dc:language>en</dc:language></metadata><manifest>"
        '<item id="p" href="p.xhtml" media-type="application/xhtml+xml"/>'
        f'<item id="i" href="img/{quote(name)}" media-type="image/png"/></manifest>'
        '<spine><itemref idref="p"/></spine></package>'
    )
    container = (
        f'<container version="1.0" xmlns="{NS["c"]}"><rootfiles><rootfile full-path="content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    files = {
        "META-INF/container.xml": container,
        "content.opf": opf,
        "p.xhtml": page,
        f"img/{name}": image_bytes((100, 100), "PNG"),
    }
    src = make_epub(tmp_path / "root.epub", files)
    z, _ = run(tmp_path, src, X4)
    assert manifest(z)["img/my pic ü.jpg"].get("href") == "img/my%20pic%20%C3%BC.jpg"
    assert 'src="img/my%20pic%20%C3%BC.jpg"' in text_of(z, "p.xhtml")
    assert "eco-eink.css" in z.namelist() and 'href="eco-eink.css"' in text_of(z, "p.xhtml")
    check_package(z)


@pytest.mark.parametrize("device", ["x4", "general"])
def test_the_builders_own_epub_is_optimized_into_a_sound_package(tmp_path, small_book, device):
    built = tmp_path / "built.epub"
    build_epub(load_source(small_book), built, device=device)
    z, rep = run(tmp_path, built, Options(device=device))
    check_package(z)
    assert rep.findings == [] and {"OEBPS/text/ch001.xhtml", "OEBPS/nav.xhtml"} <= set(z.namelist())
    assert [p for p in spine(z) if p.startswith("OEBPS/text/ch")] == [
        "OEBPS/text/ch001.xhtml",
        "OEBPS/text/ch002.xhtml",
    ]


def test_optimizing_an_optimized_epub_changes_nothing_more(tmp_path, messy_epub):
    for options in (X4, GENERAL):
        first, _ = run(tmp_path, messy_epub, options, "one.epub")
        second, rep = run(tmp_path, tmp_path / "one.epub", options, "two.epub")
        assert second.namelist() == first.namelist()
        assert manifest(second).keys() == manifest(first).keys()
        assert spine(second) == spine(first)
        assert [f.kind for f in rep.findings if f.level == "warning"] == []
        for page, item in manifest(second).items():
            if item.get("media-type") == XHTML:
                root = ET.fromstring(second.read(page))
                sheets = [
                    link
                    for link in root.iterfind(".//h:link", NS)
                    if "eco-eink" in link.get("href")
                ]
                assert len(sheets) == (1 if options is X4 else 0), page
        check_package(second)


def test_report_counts_compressed_bytes_per_category(tmp_path, messy_epub):
    z, rep = run(tmp_path, messy_epub)
    assert set(rep.before) == set(rep.after) == {"images", "fonts", "text", "other"}
    assert sum(rep.before.values()) == sum(
        i.compress_size for i in zipfile.ZipFile(messy_epub).infolist()
    )
    assert sum(rep.after.values()) == sum(i.compress_size for i in z.infolist())
    assert rep.before["fonts"] > 0 and rep.after["fonts"] == 0
    assert rep.after["images"] < rep.before["images"] // 2
    assert isinstance(rep, OptimizeReport)


def test_the_input_is_never_overwritten(tmp_path, messy_epub):
    before = messy_epub.read_bytes()
    with pytest.raises(ValueError, match="same file"):
        optimize_epub(messy_epub, messy_epub, X4)
    with pytest.raises(ValueError, match="same file"):
        optimize_epub(messy_epub, tmp_path / "sub" / ".." / messy_epub.name, X4)
    assert messy_epub.read_bytes() == before


def test_a_hard_link_to_the_input_is_not_an_output(tmp_path, messy_epub):
    link = tmp_path / "link.epub"
    os.link(messy_epub, link)
    before = messy_epub.read_bytes()
    with pytest.raises(ValueError, match="same file"):
        optimize_epub(messy_epub, link, X4)
    assert messy_epub.read_bytes() == before


def test_the_input_under_a_name_in_another_case_is_not_an_output(tmp_path, messy_epub):
    swapped = messy_epub.with_name(messy_epub.name.upper())
    if not swapped.exists():
        pytest.skip("the filesystem tells names apart by case")
    before = messy_epub.read_bytes()
    with pytest.raises(ValueError, match="same file"):
        optimize_epub(messy_epub, swapped, X4)
    assert messy_epub.read_bytes() == before


def test_a_file_that_is_not_an_epub_is_a_clear_error(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match=r"Not a readable EPUB: bad\.epub"):
        optimize_epub(bad, tmp_path / "o.epub", X4)
    bare = make_epub(tmp_path / "bare.epub", {"a.txt": b"x"})
    with pytest.raises(ValueError, match=r"Not a readable EPUB: bare\.epub"):
        optimize_epub(bare, tmp_path / "o.epub", X4)


def test_epubcheck_export_optimized(tmp_path, messy_epub):
    out = os.environ.get("ECO_EPUBCHECK_DIR")
    if not out:
        pytest.skip("ECO_EPUBCHECK_DIR is not set")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for device in ("x4", "general"):
        optimize_epub(messy_epub, out / f"messy-{device}.epub", Options(device=device))


def test_x4_reports_relative_sizes_and_removed_colors(tmp_path):
    src = package(
        tmp_path,
        {"a": f'{LINK}<p style="font-size:10px;color:gray">t</p>'},
        files={"css/s.css": "p{font-size:12pt}"},
    )
    z, report = run(tmp_path, src)
    page = text_of(z, "OEBPS/text/a.xhtml")
    assert "color" not in page and "font-size:0.625em" in page
    assert "font-size:1em" in z.read("OEBPS/css/s.css").decode()
    assert {"css_sizes_relative", "css_colors_removed"} <= set(kinds(report))


def test_an_image_only_in_a_removed_background_goes_on_x4(tmp_path):
    files = {
        "img/bg.jpg": image_bytes((100, 100), "JPEG", seed=4),
        "css/s.css": ".a{background:url(../img/bg.jpg)}",
    }
    src = package(tmp_path, {"c": f"{LINK}<p class='a'>t</p>"}, files)
    z, _ = run(tmp_path, src, X4)
    check_package(z)
    assert "OEBPS/img/bg.jpg" not in z.namelist()
    z, _ = run(tmp_path, src, GENERAL)
    assert "OEBPS/img/bg.jpg" in z.namelist()


def empty_page_book(tmp_path):
    pages = {
        "a": '<p><a href="blank.xhtml">go</a></p><p>&#160;</p>',
        "blank": "<p>&#160;</p>",
        "c": "<p>c</p>",
    }
    return package(tmp_path, pages)


def test_links_to_an_empty_document_move_to_the_next(tmp_path):
    z, report = run(tmp_path, empty_page_book(tmp_path))
    check_package(z)
    assert "OEBPS/text/blank.xhtml" not in z.namelist()
    assert "OEBPS/text/blank.xhtml" not in manifest(z)
    assert "OEBPS/text/blank.xhtml" not in spine(z)
    assert 'href="c.xhtml"' in text_of(z, "OEBPS/text/a.xhtml")
    assert "empty_removed" in kinds(report)


def test_general_keeps_empty_pages(tmp_path):
    z, report = run(tmp_path, empty_page_book(tmp_path), GENERAL)
    assert "OEBPS/text/blank.xhtml" in z.namelist() and "empty_removed" not in kinds(report)
