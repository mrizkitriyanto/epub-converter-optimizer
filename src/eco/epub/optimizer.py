import base64
import binascii
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from html.entities import html5
from io import BytesIO
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote, unquote_to_bytes, urlsplit, urlunsplit

from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image

from eco.epub.cleanup import drop_empty_blocks, is_empty_document
from eco.epub.css import rewrite_css
from eco.epub.focus import focus_body
from eco.epub.images import ImageResult, transform_image
from eco.epub.split import anchors, split_document
from eco.epub.zipio import check_expansion, write_epub_zip
from eco.events import Finding
from eco.options import CHAPTER_LIMIT_BYTES, DEVICES, Options, image_profile

XHTML = "http://www.w3.org/1999/xhtml"
SVG = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
OPF = "http://www.idpf.org/2007/opf"
for _prefix, _uri in (
    ("epub", "http://www.idpf.org/2007/ops"),
    ("svg", SVG),
    ("xlink", "http://www.w3.org/1999/xlink"),
    ("dc", "http://purl.org/dc/elements/1.1/"),
    ("enc", "http://www.w3.org/2001/04/xmlenc#"),
):
    ET.register_namespace(_prefix, _uri)

XHTML_TYPE = "application/xhtml+xml"
NCX_TYPE = "application/x-dtbncx+xml"
_EINK_CSS = (
    "img{max-width:100%;height:auto} pre{white-space:pre-wrap} table{border-collapse:collapse}"
)
_XML_DECLARATION = b'<?xml version="1.0" encoding="utf-8"?>\n'
_FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
_DOCTYPE = re.compile(rb"<!DOCTYPE[^\[>]*(?:\[.*?\])?\s*>", re.DOTALL | re.IGNORECASE)
_DATA_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/tiff": "tif",
    "image/bmp": "bmp",
}
# ponytail: srcset, <object data> and the references inside .svg files are not followed
_REF_ATTRS = ("src", "href", XLINK_HREF)
_RASTER = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
_FONTS = {".otf", ".ttf", ".woff", ".woff2", ".eot"}
_TEXT = {".xhtml", ".html", ".htm", ".css", ".ncx", ".opf", ".xml", ".txt", ".js"}
# ponytail: links to other parts add bytes after the cut. 5% of the limit leaves room for about
# 150 of them per part; a part that still ends up over the limit is reported, not split again.
_RELINK_SLACK = CHAPTER_LIMIT_BYTES // 20
# No real book has an entry or a whole that unpacks to this much; a zip bomb does. A comic
# book of full-page scans reaches a few hundred MB in all.
_MAX_ENTRY = 200 * 10**6
_MAX_TOTAL = 2000 * 10**6


class DRMError(Exception):
    pass


@dataclass
class OptimizeReport:
    findings: list[Finding]
    before: dict[str, int]  # compressed bytes in the zip, per category
    after: dict[str, int]


def _local(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _numeric(m: re.Match) -> bytes:
    """`&nbsp;` and the like become character references: the five XML entities are the only
    named ones an XML parser knows."""
    name = m[1].decode()
    if name in _XML_ENTITIES or f"{name};" not in html5:
        return m[0]
    return "".join(f"&#{ord(char)};" for char in html5[f"{name};"]).encode()


def _prefix_opf_attributes(root: ET.Element) -> None:
    """ElementTree drops the prefix of an attribute in the default namespace (opf:role="aut")."""
    namespace = f"{{{OPF}}}"
    for el in root.iter():
        for key in [key for key in el.attrib if key.startswith(namespace)]:
            el.set(f"opf:{key[len(namespace) :]}", el.attrib.pop(key))
            root.set("xmlns:opf", OPF)


class _Doc:
    """An XML file of the package. It is written back byte for byte unless something changed."""

    def __init__(self, root: ET.Element, doctype: bytes = b"", raw: bytes | None = None):
        self.root, self.doctype, self.raw = root, doctype, raw
        self.base = self.dump() if raw is not None else b""

    @classmethod
    def parse(cls, data: bytes) -> "_Doc":
        fixed = _ENTITY.sub(_numeric, data)
        root = ET.fromstring(fixed)
        if root.tag == f"{{{OPF}}}package":
            _prefix_opf_attributes(root)
        doctype = _DOCTYPE.search(fixed[:4096])
        return cls(root, doctype[0] + b"\n" if doctype else b"", data if fixed == data else None)

    def dump(self) -> bytes:
        if self.root.tag.startswith("{"):
            ET.register_namespace("", self.root.tag[1:].partition("}")[0])
        body = ET.tostring(self.root, encoding="utf-8")
        return _XML_DECLARATION + self.doctype + body + b"\n"

    def data(self) -> bytes:
        out = self.dump()
        return self.raw if self.raw is not None and out == self.base else out


def _split_url(ref: str):
    try:
        return urlsplit(ref)
    except ValueError:
        return None


def _resolve(owner: str, ref: str) -> str | None:
    """The zip path a relative reference in `owner` points at; None for URLs and empty paths."""
    parts = _split_url(ref)
    if parts is None or parts.scheme or parts.netloc or not parts.path:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner), unquote(parts.path)))


def _rel(owner: str, target: str) -> str:
    return quote(posixpath.relpath(target, posixpath.dirname(owner) or "."))


def _relative(owner: str, target: str, ref: str) -> str:
    """`ref` pointed at `target` instead; its query and fragment stay."""
    parts = urlsplit(ref)
    return urlunsplit(("", "", _rel(owner, target), parts.query, parts.fragment))


def _unsafe_name(name: str) -> bool:
    """True for a zip entry name that could land outside the folder it is unpacked into: a root, a
    drive, a backslash (Python reads it as "/" on Windows only) or a ".." part."""
    return (
        name.startswith("/")
        or "\\" in name
        or bool(PureWindowsPath(name).drive)
        or ".." in name.split("/")
    )


def _prune(parent: ET.Element, drop: Callable[[ET.Element], bool]) -> int:
    """Remove the descendants `drop` picks, with their subtrees; the text after them stays."""
    removed, previous = 0, None
    for child in list(parent):
        if drop(child):
            if child.tail:
                if previous is None:
                    parent.text = (parent.text or "") + child.tail
                else:
                    previous.tail = (previous.tail or "") + child.tail
            parent.remove(child)
            removed += 1
        else:
            removed += _prune(child, drop)
            previous = child
    return removed


def _wrapped_image(svg: ET.Element) -> str | None:
    """The href of the <image> that is the only thing an <svg> shows, if it is."""
    shown = [child for child in svg if _local(child) not in ("title", "desc", "metadata")]
    if len(shown) == 1 and shown[0].tag == f"{{{SVG}}}image":
        return shown[0].get(XLINK_HREF) or shown[0].get("href")
    return None


def _unwrap_svg(parent: ET.Element) -> None:
    """Turn the usual cover wrapper <svg><image xlink:href=X/></svg> into <img src=X alt=""/>."""
    for index, child in enumerate(parent):
        href = _wrapped_image(child) if child.tag == f"{{{SVG}}}svg" else None
        if href:
            img = ET.Element(f"{{{XHTML}}}img", {"src": href, "alt": ""})
            img.tail = child.tail
            parent[index] = img
        else:
            _unwrap_svg(child)


def _is_font(path: str, media: str) -> bool:
    suffix = posixpath.splitext(path)[1].lower()
    return suffix in _FONTS or "font" in media or media == "application/vnd.ms-opentype"


def _is_raster(path: str, media: str) -> bool:
    suffix = posixpath.splitext(path)[1].lower()
    return suffix in _RASTER or media.startswith("image/") and "svg" not in media


def _subset(data: bytes, text: str) -> bytes:
    font = TTFont(BytesIO(data))
    # a stylesheet can show the other case (text-transform, small caps) and any layout feature
    subsetter = subset.Subsetter(subset.Options(layout_features=["*"]))
    subsetter.populate(text=text + text.upper() + text.lower())
    subsetter.subset(font)
    out = BytesIO()
    font.save(out)  # the flavor (woff, woff2) is the input's
    return out.getvalue()


def _category(name: str) -> str:
    suffix = posixpath.splitext(name)[1].lower()
    if suffix in _RASTER or suffix == ".svg":
        return "images"
    if suffix in _FONTS:
        return "fonts"
    return "text" if suffix in _TEXT else "other"


def _sizes(infos: list[zipfile.ZipInfo]) -> dict[str, int]:
    totals = dict.fromkeys(("images", "fonts", "text", "other"), 0)
    for info in infos:
        totals[_category(info.filename)] += info.compress_size
    return totals


def _encryption(data: bytes | None) -> list[tuple[str, str]]:
    """The (algorithm, resource) pairs of META-INF/encryption.xml."""
    try:
        root = ET.fromstring(data or b"")
    except ET.ParseError:
        return []
    pairs = []
    for entry in root.iterfind(".//{*}EncryptedData"):
        method, ref = entry.find(".//{*}EncryptionMethod"), entry.find(".//{*}CipherReference")
        if method is not None:
            uri = unquote(ref.get("URI", "")) if ref is not None else ""
            pairs.append((method.get("Algorithm", ""), uri))
    return pairs


class _Package:
    def __init__(self, src: Path, options: Options):
        self.name = src.name
        self.options = options
        self.profile = image_profile(options)
        self.xteink = DEVICES[options.device] is not None
        self.findings: list[Finding] = []
        self.files: dict[str, bytes] = {}
        self.docs: dict[str, _Doc] = {}  # the package file, the XHTML pages and the NCX
        self.unparsed: list[str] = []  # the text of the pages and NCX that do not parse
        self.items: dict[str, ET.Element] = {}  # manifest items by zip path
        self.removed: set[str] = set()
        self.renamed: dict[str, str] = {}
        self.data_uris: dict[str, str] = {}  # data: URI -> the file that holds it
        self.obfuscated: set[str] = set()
        self.dropped = 0
        self.small: set[str] = set()  # images removed for being too small to see
        self._read(src)
        try:
            self._load()
        except RecursionError as exc:  # XML nested thousands of levels deep
            raise self._unreadable() from exc

    def _note(self, kind: str, level: str, message: str) -> None:
        self.findings.append(Finding(0, kind, level, message))

    def _unreadable(self) -> ValueError:
        return ValueError(f"Not a readable EPUB: {self.name}")

    def _read(self, src: Path) -> None:
        unsafe = 0
        try:
            with zipfile.ZipFile(src) as z:
                check_expansion(z, self.name)
                infos = [info for info in z.infolist() if not info.is_dir()]
                # zipfile reads no more than the size an entry declares, so this bounds memory
                big = max((info.file_size for info in infos), default=0) > _MAX_ENTRY
                if big or sum(info.file_size for info in infos) > _MAX_TOTAL:
                    what = "an entry of it" if big else "it"
                    limit = _MAX_ENTRY if big else _MAX_TOTAL
                    raise ValueError(
                        f"Not a readable EPUB: {self.name}: {what} unpacks to more than "
                        f"{limit // 10**6} MB"
                    )
                self.before = _sizes(infos)
                for info in infos:
                    if _unsafe_name(info.filename):
                        unsafe += 1
                    else:
                        # a bounded read: z.read(info) lets one decompress call run to 1 GiB when
                        # the directory understates the size
                        with z.open(info) as entry:
                            self.files[info.filename] = entry.read(info.file_size)
        except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError) as exc:
            raise self._unreadable() from exc
        if unsafe:
            noun = "zip entry" if unsafe == 1 else "zip entries"
            self._note("unsafe_path", "warning", f"{unsafe} {noun} with an unsafe path skipped")
        drm = DRMError(f"EPUB is DRM-protected: {self.name}")
        if "META-INF/rights.xml" in self.files:
            raise drm
        for algorithm, uri in _encryption(self.files.get("META-INF/encryption.xml")):
            if algorithm not in _FONT_OBFUSCATION:
                raise drm
            self.obfuscated.add(uri)

    def _load(self) -> None:
        try:
            container = ET.fromstring(self.files["META-INF/container.xml"])
            self.opf_path = container.find(".//{*}rootfile").get("full-path")
            self.opf = self.docs[self.opf_path] = _Doc.parse(self.files[self.opf_path])
        except (KeyError, AttributeError, ET.ParseError) as exc:
            raise self._unreadable() from exc
        self.manifest = self.opf.root.find("{*}manifest")
        self.spine = self.opf.root.find("{*}spine")
        if self.manifest is None or self.spine is None:
            raise self._unreadable()
        for item in self.manifest.findall("{*}item"):
            path = _resolve(self.opf_path, item.get("href", ""))
            if path is not None:
                self.items[path] = item
        for path, item in self.items.items():
            if path in self.files and item.get("media-type") in (XHTML_TYPE, NCX_TYPE):
                try:
                    self.docs[path] = _Doc.parse(self.files[path])
                except ET.ParseError as exc:
                    self.unparsed.append(self.files[path].decode("utf-8", "replace"))
                    message = (
                        f"{path} is not well-formed and was left unchanged, so its links are not "
                        f"updated: {exc}"
                    )
                    self._note("bad_xml", "warning", message)

    def run(self) -> None:
        self._extract_data_uris()
        self._svg()
        self._drop_unreferenced()
        self._images()
        self._fonts()
        if self.xteink:
            self._drop_empty()
        self._references()
        if self.xteink:  # a file only a removed background used is unused now
            self._drop_unreferenced()
        if self.options.style.focus_mode:
            for _, doc in self._pages():
                if (body := doc.root.find("{*}body")) is not None:
                    focus_body(body, self.options.style.focus_weight)
        if self.xteink:
            self._split_chapters()
        self._tidy()
        self._firmware_notes()

    def output(self) -> dict[str, bytes]:
        return {**self.files, **{path: doc.data() for path, doc in self.docs.items()}}

    def _pages(self) -> list[tuple[str, _Doc]]:
        return [
            (path, self.docs[path])
            for path, item in self.items.items()
            if path in self.docs and item.get("media-type") == XHTML_TYPE
        ]

    def _href(self, path: str) -> str:
        return quote(posixpath.relpath(path, posixpath.dirname(self.opf_path) or "."))

    def _free(self, path: str) -> str:
        """`path`, or `stem-1.ext`, `stem-2.ext` and so on when the name is taken."""
        stem, ext = posixpath.splitext(path)
        taken = (self.files, self.docs, self.removed, self.renamed)
        name, n = path, 0
        while any(name in names for names in taken):
            n += 1
            name = f"{stem}-{n}{ext}"
        return name

    def _add_item(
        self, path: str, media: str, after: ET.Element | None = None, stem: str = ""
    ) -> ET.Element:
        taken = {item.get("id") for item in self.manifest}
        base = stem or posixpath.splitext(posixpath.basename(path))[0]
        ident, n = base, 0
        while ident in taken:
            n += 1
            ident = f"{base}-{n}"
        namespace = self.manifest.tag[: self.manifest.tag.find("}") + 1]
        item = ET.Element(
            f"{namespace}item", {"id": ident, "href": self._href(path), "media-type": media}
        )
        item.tail = "\n"
        position = list(self.manifest).index(after) + 1 if after is not None else len(self.manifest)
        self.manifest.insert(position, item)
        self.items[path] = item
        return item

    def _remove(self, path: str) -> None:
        self.files.pop(path, None)
        self.docs.pop(path, None)
        item = self.items.pop(path, None)
        if item is not None:
            self.manifest.remove(item)
        self.removed.add(path)

    def _retarget(self, owner: str, ref: str) -> str | None:
        """`ref` after the renames, or None when the file it points at is gone."""
        target = _resolve(owner, ref)
        if target in self.removed:
            return None
        new = self.renamed.get(target)
        return ref if new is None else _relative(owner, new, ref)

    def _css(
        self, retarget_for: Callable[[str], Callable[[str], str | None]], xteink: bool
    ) -> None:
        """Rewrite every stylesheet, <style> element and style attribute; `retarget_for(owner)`
        gives the url callback of the file the CSS sits in."""
        counts: Counter = Counter()
        for path, doc in self._pages():
            retarget = retarget_for(path)
            for el in doc.root.iter():
                if _local(el) == "style" and el.text:
                    el.text = rewrite_css(el.text, retarget, xteink, counts)
                if el.get("style"):
                    style = rewrite_css(el.get("style"), retarget, xteink, counts)
                    if style.strip():
                        el.set("style", style)
                    else:
                        del el.attrib["style"]
        for path, item in list(self.items.items()):
            if item.get("media-type") == "text/css" and path in self.files:
                text = self.files[path].decode("utf-8", "surrogateescape")
                new = rewrite_css(text, retarget_for(path), xteink, counts)
                if new != text:
                    self.files[path] = new.encode("utf-8", "surrogateescape")
        if counts["sizes"]:
            self._note(
                "css_sizes_relative",
                "info",
                f"{_count(counts['sizes'], 'fixed size')} made relative",
            )
        if counts["colors"]:
            message = f"{_count(counts['colors'], 'color declaration')} removed"
            self._note("css_colors_removed", "info", message)

    def _extract_data_uris(self) -> None:
        for path, doc in self._pages():
            for el in doc.root.iter():
                for attr in _REF_ATTRS:
                    if el.get(attr, "").lstrip().startswith("data:"):
                        el.set(attr, self._save_data(path, el.get(attr)))
        self._css(lambda owner: partial(self._save_data, owner), xteink=False)

    def _save_data(self, owner: str, ref: str) -> str:
        """The reference to a file that holds the image of a data: URI, or `ref` if it is no image
        (or is broken)."""
        uri = ref.strip()
        if uri not in self.data_uris:
            head, _, payload = uri[5:].partition(",")
            mime, *params = (part.strip().lower() for part in head.split(";"))
            ext = _DATA_EXT.get(mime)
            try:
                if "base64" in params:
                    data = base64.b64decode("".join(payload.split()), validate=True)
                else:
                    data = unquote_to_bytes(payload)
            except binascii.Error:
                data = b""
            if ext is None or not data:
                return ref
            name = f"images/data-{len(self.data_uris) + 1}.{ext}"
            path = self._free(posixpath.join(posixpath.dirname(self.opf_path), name))
            self.files[path] = data
            self._add_item(path, "image/jpeg" if ext == "jpg" else mime)
            self.data_uris[uri] = path
        return _rel(owner, self.data_uris[uri])

    def _svg(self) -> None:
        """Xteink readers show no SVG: cover wrappers become <img>, everything else goes."""
        if not self.xteink:
            return
        inline = files = 0
        for _, doc in self._pages():
            _unwrap_svg(doc.root)
            inline += _prune(doc.root, lambda el: el.tag == f"{{{SVG}}}svg")
        for path, item in list(self.items.items()):
            if item.get("media-type") == "image/svg+xml" or path.lower().endswith(".svg"):
                self._remove(path)
                files += 1
        if inline or files:
            what = [
                _count(n, noun)
                for n, noun in ((inline, "inline SVG graphic"), (files, "SVG file"))
                if n
            ]
            self._note(
                "svg_removed",
                "warning",
                f"{' and '.join(what)} removed: Xteink readers show no SVG",
            )

    def _cover(self) -> str | None:
        """The cover image: the cover-image item, else the item the cover meta names."""
        for path, item in self.items.items():
            if "cover-image" in item.get("properties", "").split():
                return path
        by_id = {item.get("id"): path for path, item in self.items.items()}
        for meta in self.opf.root.iterfind(".//{*}meta"):
            if meta.get("name") == "cover":
                return by_id.get(meta.get("content"))
        return None

    def _corpus(self) -> str:
        """All the text a reference to a file can sit in: the package file without its manifest,
        pages, NCX, stylesheets and SVG files."""
        parts = [
            ET.tostring(child, encoding="unicode")
            for child in self.opf.root
            if child is not self.manifest
        ]
        for path, data in self.files.items():
            if path in self.docs and path != self.opf_path:
                parts.append(ET.tostring(self.docs[path].root, encoding="unicode"))
            elif path.lower().endswith(
                (".css", ".svg", ".xhtml", ".html", ".htm", ".ncx", ".smil")
            ):
                parts.append(data.decode("utf-8", "replace"))
        return "\n".join(parts)

    def _drop_unreferenced(self) -> None:
        """Remove the images, fonts, stylesheets and pages that nothing uses; in doubt, keep."""
        text = self._corpus()
        used = {ref.get("idref") for ref in self.spine.findall("{*}itemref")}
        used |= {item.get(attr) for item in self.manifest for attr in ("fallback", "media-overlay")}
        cover = self._cover()
        for path, item in list(self.items.items()):
            media, name = item.get("media-type", ""), posixpath.basename(path)
            candidate = media in (XHTML_TYPE, "text/css") or media.startswith("image/")
            if (candidate or _is_font(path, media)) and path != cover:
                if item.get("id") in used or "nav" in item.get("properties", "").split():
                    continue
                # ponytail: a name match can keep a file nothing uses, but never drops a used one
                if name not in text and quote(name) not in text:
                    self._remove(path)

    def _images(self) -> None:
        cover = self._cover()
        for path, item in list(self.items.items()):
            if path not in self.files or not _is_raster(path, item.get("media-type", "")):
                continue
            name = posixpath.basename(path)
            names = "|".join(re.escape(n) for n in {name, quote(name)})
            # a whole name in a link: after a quote or "/", and not followed by more of a name
            reference = re.compile(rf"""(?<=["'/])(?:{names})(?![\w.%-])""")
            if any(reference.search(text) for text in self.unparsed):
                message = f"{path} is left unchanged: a page that is not well-formed refers to it"
                self._note("image_kept", "warning", message)
                continue
            # a library needs the cover even when the other images are dropped
            profile = replace(self.profile, drop_images=False) if path == cover else self.profile
            try:
                result = transform_image(self.files[path], profile)
            except (OSError, Image.DecompressionBombError) as exc:
                fate = "removed" if self.xteink else "kept unchanged"
                self._note("image_error", "warning", f"{path} is unreadable ({exc}) and {fate}")
                if self.xteink:
                    self._remove(path)
                continue
            if result is None:
                if self.profile.drop_images:
                    self.dropped += 1
                else:  # too small to see on the screen
                    self.small.add(path)
                self._remove(path)
            else:
                self._store(path, item, result)
        if self.small:
            message = (
                f"{_count(len(self.small), 'image')} under {self.profile.min_px} px removed, too "
                "small to see on the screen; the alt text of each stays as text"
            )
            self._note("image_too_small", "info", message)

    def _store(self, path: str, item: ET.Element, result: ImageResult) -> None:
        """Keep the new bytes under the old name, or a new one if the extension changed."""
        stem, ext = posixpath.splitext(path)
        ext = ext[1:].lower()
        if {"jpeg": "jpg"}.get(ext, ext) != result.ext:
            new = self._free(f"{stem}.{result.ext}")
            del self.files[path], self.items[path]
            self.items[new] = item
            self.renamed[path] = new
            item.set("href", self._href(new))
            path = new
        self.files[path] = result.data
        item.set("media-type", result.media_type)

    def _text(self) -> str:
        """The characters a reader can see: page text and stylesheets."""
        texts = ["".join(doc.root.itertext()) for _, doc in self._pages()]
        for path, item in self.items.items():
            if item.get("media-type") == "text/css" and path in self.files:
                texts.append(self.files[path].decode("utf-8", "replace"))
        return "".join(texts)

    def _fonts(self) -> None:
        fonts = [
            p
            for p, i in self.items.items()
            if p in self.files and _is_font(p, i.get("media-type", ""))
        ]
        if self.xteink and fonts:
            for path in fonts:
                self._remove(path)
            self._note(
                "font_removed", "info", f"{_count(len(fonts), 'embedded font file')} removed"
            )
            return
        text = self._text() if fonts else ""
        for path in fonts:
            if path in self.obfuscated:
                self._note("font_kept", "info", f"{path} kept unchanged: it is obfuscated")
                continue
            try:  # fontTools raises whatever a broken font or a missing brotli causes
                data = _subset(self.files[path], text)
            except Exception as exc:  # noqa: BLE001
                self._note(
                    "font_kept", "info", f"{path} kept unchanged: {exc or type(exc).__name__}"
                )
                continue
            if len(data) < len(self.files[path]):
                self.files[path] = data

    def _references(self) -> None:
        """Follow the renames and removals in every reference; on Xteink also filter the CSS and
        add the e-ink stylesheet."""
        self._css(lambda owner: partial(self._retarget, owner), self.xteink)
        for path, doc in self._pages():
            dead = set()
            for el in doc.root.iter():
                for attr in _REF_ATTRS:
                    ref = el.get(attr)
                    new = None if ref is None else self._retarget(path, ref)
                    if ref is None or new == ref:
                        continue
                    if new is not None:
                        el.set(attr, new)
                    elif _local(el) == "a":
                        del el.attrib[attr]  # the link text stays
                    else:
                        if _local(el) == "img" and _resolve(path, ref) in self.small:
                            el.tail = el.get("alt", "") + (el.tail or "")  # _prune keeps it
                        dead.add(el)
            if dead:
                _prune(doc.root, dead.__contains__)
        for path, item in self.items.items():  # the NCX follows renames, as the pages do
            if item.get("media-type") == NCX_TYPE and path in self.docs:
                for el in self.docs[path].root.iter():
                    ref = el.get("src") if _local(el) == "content" else None
                    new = None if ref is None else self._retarget(path, ref)
                    if new is not None and new != ref:
                        el.set("src", new)
        if not self.xteink:
            return
        sheet = next((p for p in self.items if posixpath.basename(p) == "eco-eink.css"), None)
        if sheet is None:  # an EPUB that eco optimized before already has it
            sheet = self._free(posixpath.join(posixpath.dirname(self.opf_path), "eco-eink.css"))
            self.files[sheet] = _EINK_CSS.encode()
            self._add_item(sheet, "text/css", stem="eco-eink")
        for path, doc in self._pages():
            head = doc.root.find("{*}head")
            href = _rel(path, sheet)
            if head is not None and all(
                link.get("href") != href for link in head.iterfind("{*}link")
            ):
                ET.SubElement(
                    head,
                    f"{{{XHTML}}}link",
                    {"rel": "stylesheet", "type": "text/css", "href": href},
                )

    def _drop_empty(self) -> None:
        """Xteink: empty paragraphs and empty pages go. A page with nothing to read is renamed to
        the next page that remains, so every link to it moves there."""
        blocks = 0
        for _, doc in self._pages():
            if (body := doc.root.find("{*}body")) is not None:
                blocks += drop_empty_blocks(body)
        by_id = {item.get("id"): path for path, item in self.items.items()}
        order = [by_id.get(ref.get("idref")) for ref in self.spine.findall("{*}itemref")]
        order = [
            p for p in order if p in self.docs and self.items[p].get("media-type") == XHTML_TYPE
        ]
        empty = []
        for path in order:
            body = self.docs[path].root.find("{*}body")
            nav = "nav" in self.items[path].get("properties", "").split()
            if body is not None and not nav and is_empty_document(body):
                empty.append(path)
        left = [p for p in order if p not in empty]
        if not left:
            empty = []  # a book of nothing keeps its pages
        for path in empty:
            index = order.index(path)
            after = [p for p in order[index + 1 :] if p in left]
            self.renamed[path] = after[0] if after else [p for p in order[:index] if p in left][-1]
            self.files.pop(path, None)
            self.docs.pop(path, None)
            self.manifest.remove(self.items.pop(path))
        parts = []
        if blocks:
            parts.append(_count(blocks, "empty paragraph"))
        if empty:
            parts.append(_count(len(empty), "empty page"))
        if parts:
            self._note("empty_removed", "info", f"{' and '.join(parts)} removed")

    def _split_chapters(self) -> None:
        by_id = {item.get("id"): path for path, item in self.items.items()}
        splits: dict[str, list[str]] = {}  # a file that was split -> its parts, the file first
        where: dict[str, dict[str, str]] = {}  # a split file -> {anchor: the part that holds it}
        for ref in self.spine.findall("{*}itemref"):
            path = by_id.get(ref.get("idref"))
            item, doc = self.items.get(path), self.docs.get(path)
            if doc is None or item is None or item.get("media-type") != XHTML_TYPE:
                continue
            if (
                "nav" in item.get("properties", "").split()
                or len(doc.data()) <= CHAPTER_LIMIT_BYTES
            ):
                continue
            room = CHAPTER_LIMIT_BYTES - len(_XML_DECLARATION + doc.doctype) - _RELINK_SLACK
            parts = split_document(doc.root, room)
            if len(parts) == 1:
                message = f"{path} is over the limit and cannot be split: one element holds it all"
                self._note("chapter_split", "warning", message)
                continue
            stem, ext = posixpath.splitext(path)
            names = [path, *(self._free(f"{stem}-{n}{ext}") for n in range(2, len(parts) + 1))]
            before_item, before_ref = item, ref
            for number, (name, part) in enumerate(zip(names, parts), 1):
                self.docs[name] = _Doc(part, doc.doctype)
                if number > 1:
                    new = self._add_item(
                        name, XHTML_TYPE, before_item, f"{item.get('id')}-{number}"
                    )
                    if item.get("properties"):
                        new.set("properties", item.get("properties"))
                    new_ref = ET.Element(ref.tag, {**ref.attrib, "idref": new.get("id")})
                    new_ref.tail = "\n"
                    self.spine.insert(list(self.spine).index(before_ref) + 1, new_ref)
                    before_item, before_ref = new, new_ref
            splits[path] = names
            where[path] = {}
            for name, part in zip(names, parts):
                for anchor in anchors(part):
                    where[path].setdefault(anchor, name)  # the head and body repeat in every part
        if not splits:
            return
        origin = {name: path for path, names in splits.items() for name in names}
        for path, doc in self.docs.items():
            if path != self.opf_path:
                self._relink(path, doc.root, where, origin)
        for path, names in splits.items():
            over = sum(len(self.docs[name].data()) > CHAPTER_LIMIT_BYTES for name in names)
            message = f"{path} split into {len(names)} files"
            if over:
                message += f"; {over} still over the limit (one element is larger than the limit)"
            self._note("chapter_split", "warning" if over else "info", message)

    def _relink(self, path: str, root: ET.Element, where: dict, origin: dict) -> None:
        """Point `file#id` and `#id` links at the part that now holds the id."""
        for el in root.iter():
            attr = "src" if _local(el) == "content" else "href"
            ref = el.get(attr, "")
            parts = _split_url(ref)
            if parts is None or not parts.fragment or parts.scheme or parts.netloc:
                continue
            current = _resolve(path, ref) or path  # the file the link names now
            home = where.get(origin.get(current, current), {}).get(unquote(parts.fragment))
            if home is not None and home != current:
                el.set(attr, _relative(path, home, ref))

    def _tidy(self) -> None:
        """Leave no reference to what is gone, and no property that no longer applies."""
        ids = {item.get("id") for item in self.manifest}
        for ref in self.spine.findall("{*}itemref"):
            if ref.get("idref") not in ids:
                self.spine.remove(ref)
        for item in self.manifest:
            if "fallback" in item.attrib and item.get("fallback") not in ids:
                del item.attrib["fallback"]
        for parent in self.opf.root:
            for child in list(parent):
                cover = _local(child) == "meta" and child.get("name") == "cover"
                guide = _local(child) == "reference" and _resolve(
                    self.opf_path, child.get("href", "")
                )
                if cover and child.get("content") not in ids or guide and guide not in self.files:
                    parent.remove(child)
        for path, doc in self._pages():
            item = self.items[path]
            properties = item.get("properties", "").split()
            if "svg" in properties and next(doc.root.iter(f"{{{SVG}}}svg"), None) is None:
                properties.remove("svg")
                if properties:
                    item.set("properties", " ".join(properties))
                else:
                    del item.attrib["properties"]
        self._tidy_encryption()

    def _tidy_encryption(self) -> None:
        name = "META-INF/encryption.xml"
        try:
            doc = _Doc.parse(self.files[name])
        except (KeyError, ET.ParseError):
            return
        gone = [
            entry
            for entry in doc.root
            if (ref := entry.find(".//{*}CipherReference")) is not None
            and unquote(ref.get("URI", "")) not in self.files
        ]
        for entry in gone:
            doc.root.remove(entry)
        if gone and len(doc.root):
            self.files[name] = doc.dump()
        elif gone:
            del self.files[name]

    def _firmware_notes(self) -> None:
        if not (self.xteink and self.options.firmware == "stock"):
            return
        if self.dropped:
            message = (
                f"{_count(self.dropped, 'image')} dropped: stock firmware shows no EPUB images"
            )
            self._note("images_dropped", "info", message)
        kept = sum(item.get("media-type", "").startswith("image/") for item in self.items.values())
        if kept:
            message = (
                "stock firmware does not show images in EPUB files; "
                f"{_count(kept, 'image')} kept so the file stays useful after a firmware change"
            )
            self._note("stock_images", "warning", message)


def optimize_epub(src: Path, dst: Path, options: Options) -> OptimizeReport:
    """Write an optimized copy of an EPUB for the device in `options`; the input stays as it is."""
    # resolve() sees through ".." and symlinks even when dst does not exist yet; samefile() sees
    # through hard links and, on a filesystem that ignores case, a name in another case
    if dst.resolve() == src.resolve() or (dst.exists() and dst.samefile(src)):
        raise ValueError(f"The output is the same file as the input: {src.name}")
    package = _Package(src, options)
    package.run()
    # ponytail: zopfli is not used; measure before adding
    write_epub_zip(dst, package.output())
    with zipfile.ZipFile(dst) as z:
        after = _sizes(z.infolist())
    return OptimizeReport(package.findings, package.before, after)
