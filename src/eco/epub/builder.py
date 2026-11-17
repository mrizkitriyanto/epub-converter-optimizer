import html
import re
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.entities import html5
from io import BytesIO
from itertools import count
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from PIL import Image, ImageDraw, ImageFont

from eco.bookfolder import BookSource
from eco.epub.zipio import write_epub_zip
from eco.events import Finding
from eco.options import CHAPTER_LIMIT_BYTES, DEVICES

_MD = MarkdownIt("commonmark", {"html": True, "xhtmlOut": True}).enable("table")
_MD.use(footnote_plugin)

_MEDIA = {
    ".xhtml": "application/xhtml+xml",
    ".ncx": "application/x-dtbncx+xml",
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_IMAGE_SUFFIXES = {ext for ext, media in _MEDIA.items() if media.startswith("image/")}
_XML = '<?xml version="1.0" encoding="utf-8"?>\n'
_XHTML_NS = 'xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
_CONTAINER = (
    f'{_XML}<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n'
)
_CSS = "p.footnote{font-size:.8em}\nimg{max-width:100%;height:auto}\n"

_PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_TWIN = re.compile(r"<!--\s*table-image:\s*(.*?)\s*-->")
_NEWLINE = re.compile(r"\r\n?|\n")
_NOT_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]")
_ENTITY = re.compile(r"&(?:([A-Za-z][A-Za-z0-9]*);|#(?:[0-9]+|x[0-9A-Fa-f]+);)?")
_VOID = re.compile(
    r"<(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)"
    r"(?=[\s/>])([^<>]*?)\s*/?>",
    re.IGNORECASE,
)
_ALT = re.compile(r"\salt\s*=")
_IMG = re.compile(r"<img\s[^<>]*>")
_SRC = re.compile(r"""(\ssrc\s*=\s*)(["'])(.*?)\2""")
_ID = re.compile(r'\sid="([^"]+)"')
_LOCAL_LINK = re.compile(r'href="#([^"]+)"')


@dataclass
class _Chapter:
    stem: str
    title: str
    page: int = 0
    blocks: list[str] = field(default_factory=list)  # rendered XHTML, one string per block
    subs: list[tuple[str, str, int]] = field(default_factory=list)  # "##": title, id, block no.


def build_epub(src: BookSource, dst: Path, *, device: str) -> list[Finding]:
    builder = _Builder(src, device)
    write_epub_zip(dst, builder.build())
    return builder.findings


class _Builder:
    def __init__(self, src: BookSource, device: str):
        self.meta = src.meta
        self.title = src.meta["title"]
        self.lang = _esc(src.meta.get("language") or "en")
        self.screen = DEVICES[device]  # None for general e-readers
        self.base = src.base_dir.resolve()
        self.text = _NOT_XML.sub("", src.markdown)
        self.lines = _NEWLINE.split(self.text)
        source = src.meta.get("source") or self.title
        self.uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, source)}"
        self.findings: list[Finding] = []
        self.files: dict[str, bytes] = {}  # path inside OEBPS/ -> content
        self.images: dict[Path, str] = {}  # source file -> path inside OEBPS/
        self.env: dict = {}
        self.page = 0

    def build(self) -> dict[str, bytes]:
        cover = self._cover()
        toc, spine = self._chapter_files(self._chapters())
        self.files["style.css"] = _CSS.encode()
        self.files["nav.xhtml"] = self._page(self.title, _nav(toc), up="").encode()
        self.files["toc.ncx"] = self._ncx(toc).encode()
        opf = self._opf(["text/cover.xhtml", *spine], cover)
        files = {f"OEBPS/{name}": data for name, data in self.files.items()}
        files["OEBPS/content.opf"] = opf.encode()
        files["META-INF/container.xml"] = _CONTAINER.encode()
        return files

    def _note(self, kind: str, level: str, message: str) -> None:
        self.findings.append(Finding(self.page, kind, level, message))

    def _chapters(self) -> list[_Chapter]:
        chapters = [_Chapter("front", self.title)]
        twin, headings = "", 0
        for block in _blocks(_MD.parse(self.text, self.env)):
            first = block[0]
            if first.type == "html_block":
                comment = first.content.strip()
                if m := _PAGE.fullmatch(comment):
                    self.page = int(m[1])
                    continue
                if m := _TWIN.fullmatch(comment):
                    twin = m[1]
                    continue
            if first.type == "heading_open":
                headings += 1
                first.attrSet("id", f"h-{headings}")
                title = _plain(block[1]) or self.title
                if first.tag == "h1":
                    chapters.append(_Chapter(f"ch{len(chapters):03d}", title, self.page))
                elif first.tag == "h2":
                    chapters[-1].subs.append((title, f"h-{headings}", len(chapters[-1].blocks)))
            if markup := self._render(block, twin):  # a dropped image can leave nothing
                chapters[-1].blocks.append(markup)
            twin = ""
        if not chapters[0].blocks and len(chapters) > 1:
            del chapters[0]
        return chapters

    def _render(self, block: list[Token], twin: str) -> str:
        first = block[0]
        markup = _fix(_MD.renderer.render(block, _MD.options, self.env)).strip()
        root = _parse(markup)
        if root is None:
            self._note("bad_html", "warning", "malformed HTML is shown as text")
            source = "\n".join(self.lines[slice(*first.map)]) if first.map else markup
            ident = f' id="{first.attrGet("id")}"' if first.type == "heading_open" else ""
            return f"<p{ident}>{_esc(source)}</p>"
        is_table = first.type == "html_block" and markup.lstrip().startswith("<table")
        if twin and self.screen and is_table and (columns := _columns(root)) > 4:
            if self._lookup(twin):
                self._note(
                    "table_as_image", "info", f"table with {columns} columns became an image"
                )
                markup = f'<p><img src="{_esc(twin)}" alt="table" /></p>'
            else:
                self._note(
                    "missing_image", "warning", f"table image not found or unsupported: {twin}"
                )
        return _IMG.sub(self._img, markup)

    def _img(self, m: re.Match) -> str:
        tag = m[0]
        found = _SRC.search(tag)
        ref = html.unescape(found[3]) if found else ""
        if ref.startswith("data:"):
            return tag  # the optimizer extracts these
        name = self._image(ref)
        return f'{tag[: found.start()]}{found[1]}"../{name}"{tag[found.end() :]}' if name else ""

    def _lookup(self, ref: str) -> Path | None:
        try:
            path = (self.base / unquote(ref)).resolve()
        except (OSError, ValueError):
            return None
        usable = path.suffix.lower() in _IMAGE_SUFFIXES and path.is_relative_to(self.base)
        return path if usable and path.is_file() else None

    def _image(self, ref: str) -> str | None:
        path = self._lookup(ref)
        if path is None:
            self._note("missing_image", "warning", f"image not found or unsupported: {ref}")
            return None
        if path not in self.images:
            name = f"images/img-{len(self.images) + 1:03d}{path.suffix.lower()}"
            self.images[path] = name
            self.files[name] = path.read_bytes()
        return self.images[path]

    def _cover(self) -> str:
        ref = self.meta.get("cover", "")
        name = self._image(ref) if ref else None
        if name is None:
            name = "images/cover.jpg"
            self.files[name] = self._text_cover()
        body = f'<div><img src="../{name}" alt="{_esc(self.title)}" /></div>'
        self.files["text/cover.xhtml"] = self._page(self.title, body).encode()
        return name

    def _text_cover(self) -> bytes:
        # ponytail: Pillow's built-in font has Latin glyphs only; ship a font if CJK titles matter
        width, height = self.screen or (1200, 1600)
        page = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(page)
        y = height // 5
        for text, size in ((self.title, width // 12), (self.meta.get("author", ""), width // 20)):
            font = ImageFont.load_default(size=size)
            for line in _wrap(draw, text, font, width * 0.8):
                x = (width - draw.textlength(line, font=font)) / 2
                draw.text((x, y), line, fill="black", font=font)
                y += size * 1.3
            y += size
        out = BytesIO()
        page.save(out, "JPEG", quality=85)
        return out.getvalue()

    def _page(self, title: str, body: str, up: str = "../") -> str:
        lang = self.lang
        return (
            f'{_XML}<!DOCTYPE html>\n<html {_XHTML_NS} lang="{lang}" xml:lang="{lang}">\n'
            f'<head>\n<meta charset="utf-8"/>\n<title>{_esc(title)}</title>\n'
            f'<link rel="stylesheet" type="text/css" href="{up}style.css"/>\n</head>\n'
            f"<body>\n{body}\n</body>\n</html>\n"
        )

    def _chapter_files(self, chapters: list[_Chapter]) -> tuple[list[tuple], list[str]]:
        """Write each chapter as one or more files; return the TOC and the spine."""
        pages, toc = [], []
        for ch in chapters:
            room = CHAPTER_LIMIT_BYTES - len(self._page(ch.title, "").encode())
            parts, part_of, size = [[]], [], 0
            for block in ch.blocks:
                n = len(block.encode()) + 1
                if parts[-1] and size + n > room:
                    parts.append([])
                    size = 0
                parts[-1].append(block)
                part_of.append(len(parts) - 1)
                size += n
            names = [f"text/{ch.stem}{f'-{k + 1}' if k else ''}.xhtml" for k in range(len(parts))]
            pages += [(name, ch.title, "\n".join(part)) for name, part in zip(names, parts)]
            subs = [(title, f"{names[part_of[i]]}#{ident}") for title, ident, i in ch.subs]
            toc.append((ch.title, names[0], subs))
            if len(parts) > 1:
                self.page = ch.page
                self._note("chapter_split", "info", f"chapter {ch.title!r} is {len(parts)} files")
        # ponytail: relinking can grow a part a few bytes past the limit; the optimizer re-splits
        where = {ident: name for name, _, body in pages for ident in _ID.findall(body)}
        for name, title, body in pages:
            self.files[name] = self._page(title, _relink(body, name, where)).encode()
        return toc, [name for name, _, _ in pages]

    def _ncx(self, toc: list[tuple]) -> str:
        order = count(1)

        def point(title: str, href: str, subs: list[tuple] = ()) -> str:
            n = next(order)
            label = f"<navLabel><text>{_esc(title)}</text></navLabel>"
            return (
                f'<navPoint id="np-{n}" playOrder="{n}">{label}<content src="{href}"/>'
                + "".join(point(*sub) for sub in subs)
                + "</navPoint>"
            )

        depth = 2 if any(subs for *_, subs in toc) else 1
        return (
            f'{_XML}<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" '
            f'xml:lang="{self.lang}">\n<head>\n<meta name="dtb:uid" content="{self.uid}"/>\n'
            f'<meta name="dtb:depth" content="{depth}"/>\n'
            '<meta name="dtb:totalPageCount" content="0"/>\n'
            '<meta name="dtb:maxPageNumber" content="0"/>\n</head>\n'
            f"<docTitle><text>{_esc(self.title)}</text></docTitle>\n"
            f"<navMap>\n{''.join(point(*entry) for entry in toc)}\n</navMap>\n</ncx>\n"
        )

    def _opf(self, spine: list[str], cover: str) -> str:
        ids = {name: Path(name).stem for name in self.files}
        ids["toc.ncx"], ids[cover] = "ncx", "cover-image"
        special = {"nav.xhtml": ' properties="nav"', cover: ' properties="cover-image"'}
        items = "\n".join(
            f'<item id="{ids[name]}" href="{name}" media-type="{_MEDIA[Path(name).suffix]}"'
            f"{special.get(name, '')}/>"
            for name in sorted(self.files)
        )
        itemrefs = "\n".join(f'<itemref idref="{ids[name]}"/>' for name in spine)
        author = self.meta.get("author", "")
        creator = f"<dc:creator>{_esc(author)}</dc:creator>\n" if author else ""
        modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            f'{_XML}<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            f'unique-identifier="book-id" xml:lang="{self.lang}">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'<dc:identifier id="book-id">{self.uid}</dc:identifier>\n'
            f"<dc:title>{_esc(self.title)}</dc:title>\n{creator}"
            f"<dc:language>{self.lang}</dc:language>\n"
            f'<meta property="dcterms:modified">{modified}</meta>\n'
            '<meta name="cover" content="cover-image"/>\n</metadata>\n'
            f"<manifest>\n{items}\n</manifest>\n"
            f'<spine toc="ncx">\n{itemrefs}\n</spine>\n</package>\n'
        )


def _blocks(tokens: list[Token]) -> Iterator[list[Token]]:
    """Yield the tokens of each top-level block."""
    start = depth = 0
    for i, token in enumerate(tokens):
        depth += token.nesting
        if depth == 0:
            yield tokens[start : i + 1]
            start = i + 1


def _plain(inline: Token) -> str:
    text = "".join(c.content for c in inline.children or [] if c.type in ("text", "code_inline"))
    return " ".join(text.split())


def _esc(text: str) -> str:
    return html.escape(_NOT_XML.sub("", text))


def _fix(markup: str) -> str:
    """Turn raw HTML into XML.

    Named entities become characters, a bare "&" is escaped, void tags self-close.
    """
    return _VOID.sub(_void, _ENTITY.sub(_entity, markup))


def _entity(m: re.Match) -> str:
    if m[0] == "&":  # not a reference at all
        return "&amp;"
    if m[1] is None or m[1] in ("amp", "lt", "gt", "quot", "apos"):  # numeric, or XML's own
        return m[0]
    char = html5.get(f"{m[1]};")
    return html.escape(char) if char else f"&amp;{m[1]};"


def _void(m: re.Match) -> str:
    name, attrs = m[1].lower(), m[2]
    if name == "img" and not _ALT.search(attrs):
        attrs += ' alt=""'
    return f"<{name}{attrs} />"


def _parse(markup: str) -> ET.Element | None:
    try:
        return ET.fromstring(f"<div {_XHTML_NS}>{markup}</div>")
    except ET.ParseError:
        return None


def _columns(table: ET.Element) -> int:
    def span(cell: ET.Element) -> int:
        n = cell.get("colspan", "1").strip()
        return int(n) if n.isdecimal() else 1

    rows = (tr.findall("{*}td") + tr.findall("{*}th") for tr in table.iterfind(".//{*}tr"))
    return max((sum(span(cell) for cell in row) for row in rows), default=0)


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: float
) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def _relink(body: str, name: str, where: dict[str, str]) -> str:
    """Point `#id` links at the file that holds the id, when it is another file."""

    def target(m: re.Match) -> str:
        home = where.get(m[1], name)
        return m[0] if home == name else f'href="{Path(home).name}#{m[1]}"'

    return _LOCAL_LINK.sub(target, body)


def _nav(toc: list[tuple]) -> str:
    def link(title: str, href: str) -> str:
        return f'<a href="{href}">{_esc(title)}</a>'

    def items(entries: list[str]) -> str:
        return f"<ol>{''.join(f'<li>{e}</li>' for e in entries)}</ol>" if entries else ""

    entries = [link(title, href) + items([link(*sub) for sub in subs]) for title, href, subs in toc]
    return f'<nav epub:type="toc" id="toc">{items(entries)}</nav>'
