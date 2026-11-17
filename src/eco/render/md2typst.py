"""Markdown to Typst: the source the preview renderer compiles.

The converter reads the book the way the EPUB builder does (same markdown-it parser) and writes
one `main.typ` plus the image files it refers to. It writes no files itself.
"""

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from PIL import Image

from eco.bookfolder import BookSource
from eco.epub.images import transform_image
from eco.options import DEVICES, ImageProfile

VIEWS = ("crosspoint", "crossink", "stock", "xtc")

_MD = MarkdownIt("commonmark", {"html": True, "xhtmlOut": True}).enable("table")
_MD.use(footnote_plugin)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
_PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_TWIN = re.compile(r"<!--\s*table-image:\s*(.*?)\s*-->")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LANG = re.compile(r"[a-z]{2,3}")
_STOCK_BOX = "#rect(width: 100%, stroke: 1pt + gray)[Image not shown on stock firmware]"
_TWIN_MIN_COLUMNS = 5  # Xteink tables wider than 4 columns use their image twin
# What a damaged image can raise while PIL reads it. One bad image must not fail the render.
_BAD_IMAGE = (OSError, SyntaxError, ValueError, Image.DecompressionBombError)
# Formats Typst reads, by PIL format name (a multi-picture JPEG is reported as MPO).
_FORMAT_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "MPO": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
_SVG_ROOT = "{http://www.w3.org/2000/svg}svg"
_GLYPH_EM = 0.55  # average glyph width, to guess how many lines a caption takes
_FIGURE_GAP_EM = 0.65  # Typst's default gap between a figure and its caption
_MONO_EM = 0.602  # glyph advance of DejaVu Sans Mono
_RAW_EM = 0.62  # code is set at this share of the body size
_MIN_IMAGE_SHARE = 0.25  # an image keeps at least this share of the body height

# Typst markup characters, plus "~" (non-breaking space), "/" (term lists, comments) and the
# "--", "---" and "-?" shorthands.
_SPECIAL = re.compile(r"[\\#$*_`<>@\[\]~/]|-(?=[-?])")
# Text that starts a line and would turn into a list, enum item or heading.
_LINE_START_ENUM = re.compile(r"^(\d+)\.")
_LINE_START_MARK = re.compile(r"^[-+=]")
_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


@dataclass(frozen=True)
class RenderSettings:
    font_size: int = 32
    margin: int = 16
    line_height: float = 1.35
    status_bar: bool = True


def to_typst(
    src: BookSource,
    *,
    device: str,
    settings: RenderSettings,
    view: str,
    image_profile: ImageProfile | None = None,
) -> dict[str, bytes | Path]:
    """Return typst-py's multi-file input: `main.typ` plus every image the source refers to."""
    if device not in DEVICES:
        raise ValueError(f"unknown device: {device!r}")
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view!r}")
    converter = _Converter(src, device, settings, view, image_profile)
    return {"main.typ": converter.convert().encode(), **converter.files}


def _esc(text: str, line_start: bool = False) -> str:
    """Escape text for Typst markup. `line_start` is true when the text begins a line."""
    text = _SPECIAL.sub(r"\\\g<0>", text)
    if line_start:
        text = _LINE_START_ENUM.sub(r"\1\\.", text)
        text = _LINE_START_MARK.sub(r"\\\g<0>", text)
    return text


def _str(text: str) -> str:
    """The body of a Typst string literal."""
    return re.sub(
        r'[\\"\x00-\x1f]',
        lambda m: _STRING_ESCAPES.get(m[0]) or f"\\u{{{ord(m[0]):x}}}",
        text,
    )


def _pt(value: float) -> str:
    return f"{round(value, 2):g}pt"


def _words(text: str) -> str:
    return " ".join(text.split())


def _plain(inline: Token) -> str:
    text = "".join(c.content for c in inline.children or [] if c.type in ("text", "code_inline"))
    return _words(text)


def _close(tokens: list[Token], start: int) -> int:
    """Index of the token that closes the one at `start`."""
    depth = 0
    for i in range(start, len(tokens)):
        depth += tokens[i].nesting
        if depth == 0:
            return i
    return len(tokens) - 1


@dataclass
class _Cell:
    header: bool
    colspan: int
    rowspan: int
    text: str = ""


def _span(value: str | None) -> int:
    return int(value) if value and value.strip().isdecimal() else 1


class _Html(HTMLParser):
    """The tables, images and text of an HTML fragment."""

    def __init__(self, markup: str):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self.images: list[tuple[str, str]] = []  # (src, alt)
        self.caption = ""
        self.text = ""
        self._cell: _Cell | None = None
        self._in_caption = False
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            if not self.rows:
                self.rows.append([])
            self._cell = _Cell(tag == "th", _span(attr.get("colspan")), _span(attr.get("rowspan")))
            self.rows[-1].append(self._cell)
        elif tag == "img":
            self.images.append((attr.get("src") or "", attr.get("alt") or ""))
        elif tag == "figcaption":
            self._in_caption = True
        elif tag == "br":
            self.handle_data(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "figcaption":
            self._in_caption = False

    def handle_data(self, data):
        if self._cell:
            self._cell.text += data
        elif self._in_caption:
            self.caption += data
        else:
            self.text += data


class _Converter:
    def __init__(
        self,
        src: BookSource,
        device: str,
        settings: RenderSettings,
        view: str,
        profile: ImageProfile | None,
    ):
        self.meta = src.meta
        self.title = src.meta["title"]
        self.text = _CONTROL.sub("", src.markdown)
        self.base = src.base_dir.resolve()
        self.device = device
        self.settings = settings
        self.stock = view == "stock"
        self.profile = profile
        self.files: dict[str, bytes | Path] = {}
        self._found: dict[Path, tuple[str, tuple[int, int] | None] | None] = {}  # None: left out
        self._twin = ""
        self._lead: list[str] = []  # page markers that wait for the chapter heading after them
        self._env: dict = {}

    def convert(self) -> str:
        body = "\n\n".join(self._blocks(_MD.parse(self.text, self._env)))
        return f"{self._preamble()}\n{body}\n"

    def _page_size(self) -> tuple[int, int]:
        return DEVICES[self.device] or (480, 800)

    def _preamble(self) -> str:
        s = self.settings
        width, height = self._page_size()
        language = _words(self.meta.get("language") or "").lower().replace("_", "-")
        lang = language.split("-")[0]
        lang = lang if _LANG.fullmatch(lang) else "en"
        footer = ""
        if s.status_bar:
            footer = (
                ",\n  footer: context [\n    #set text(size: 12pt)\n"
                "    #grid(columns: (1fr, auto), gutter: 8pt,\n"
                "      box(width: 100%, height: 1.2em, clip: true, {\n"
                "        let found = query(selector(<chap>).before(here()))\n"
                "        if found.len() > 0 { found.last().value.title }\n"
                "      }),\n"
                "      [#counter(page).display() / #counter(page).final().first()],\n"
                "    )\n  ]"
            )
        return (
            f"#set page(width: {width}pt, height: {height}pt, "
            f"margin: (x: {s.margin}pt, top: {s.margin}pt, bottom: {s.margin + 22}pt){footer})\n"
            f'#set text(font: "Libertinus Serif", size: {s.font_size}pt, lang: "{lang}", '
            "hyphenate: true)\n"
            f"#set par(justify: true, leading: {round(s.line_height - 1, 3)}em)\n"
            '#show raw: set text(font: "DejaVu Sans Mono", size: 0.62em)\n'
            f"{self._raw_wrap()}\n"
            "#show heading.where(level: 1): it => { pagebreak(weak: true); it }\n"
            "#show figure.caption: it => it.body\n"
        )

    def _raw_wrap(self) -> str:
        """A raw line that is wider than the page runs past the edge. Zero-width spaces between the
        characters of any run of `fit` characters or more let it wrap at the page edge."""
        width = self._page_size()[0] - 2 * self.settings.margin
        fit = max(8, int(width / (_MONO_EM * _RAW_EM * self.settings.font_size)))
        return (
            "#show raw: it => {\n"
            f'  show regex("[^ ]{{{fit},}}"): m => m.text.clusters().join(sym.zws)\n'
            "  it\n}"
        )

    # Blocks

    def _blocks(self, tokens: list[Token], nested: bool = False) -> list[str]:
        out, i = [], 0
        while i < len(tokens):
            token = tokens[i]
            if token.type == "html_block":
                comment = token.content.strip()
                if m := _PAGE.fullmatch(comment):
                    marker = f"#context [#metadata((src: {m[1]}, page: here().page())) <srcpage>]"
                    # A marker right before a chapter heading goes after the chapter's page break,
                    # so it lands on the chapter's first page and not on the last page before it.
                    waits = not nested and self._chapter_follows(tokens, i)
                    (self._lead if waits else out).append(marker)
                    i += 1
                    continue
                if m := _TWIN.fullmatch(comment):
                    self._twin = m[1]
                    i += 1
                    continue
            if token.nesting == 1:
                end = _close(tokens, i)
                text = self._container(token, tokens[i + 1 : end], tokens[i : end + 1], nested)
                i = end + 1
            else:
                text = self._leaf(token)
                i += 1
            self._twin = ""
            if text:
                out.append(text)
        return out

    @staticmethod
    def _chapter_follows(tokens: list[Token], i: int) -> bool:
        """True when only page markers separate token `i` from a level-1 heading."""
        for token in tokens[i + 1 :]:
            if token.type == "html_block" and _PAGE.fullmatch(token.content.strip()):
                continue
            return token.type == "heading_open" and token.tag == "h1"
        return False

    def _leaf(self, token: Token) -> str:
        if token.type in ("fence", "code_block"):
            return f'#raw(block: true, "{_str(token.content.rstrip(chr(10)))}")'
        if token.type == "hr":
            return "#line(length: 100%, stroke: 0.5pt)"
        if token.type == "html_block":
            return self._html(token.content)
        return ""

    def _container(self, token: Token, inner: list[Token], whole: list[Token], nested: bool) -> str:
        kind = token.type
        if kind == "heading_open":
            return self._heading(int(token.tag[1]), inner[0], nested)
        if kind == "paragraph_open":
            return self._inline(inner[0].children or [])
        if kind in ("bullet_list_open", "ordered_list_open"):
            return self._list(token, inner)
        if kind == "blockquote_open":
            body = "\n\n".join(self._blocks(inner, True))
            return f"#block(inset: (left: 1em), stroke: (left: 0.5pt))[\n{body}\n]" if body else ""
        if kind == "table_open":
            return self._html(_MD.renderer.render(whole, _MD.options, self._env))
        body = "\n\n".join(self._blocks(inner, True))
        if kind == "footnote_open":
            return f"#super[{token.meta['id'] + 1}]; {body}"
        return body  # footnote_block_open and anything else that only holds blocks

    def _heading(self, level: int, inline: Token, nested: bool) -> str:
        # A page break cannot sit inside a quote or list item, so a "#" there is an ordinary
        # heading one level down (the page-break rule only matches level 1).
        level = max(level, 2) if nested else level
        text = f"{'=' * level} {self._inline(inline.children or [], start=False)}"
        if level > 1:
            return text
        title = _str(_plain(inline) or self.title)
        markers = [f'#context [#metadata((title: "{title}", page: here().page())) <chap>]']
        markers += self._lead
        self._lead = []
        # The break is explicit so the markers land on the chapter's own first page.
        return "#pagebreak(weak: true)\n" + "\n".join(markers) + f"\n{text}"

    def _list(self, token: Token, inner: list[Token]) -> str:
        number = int(token.attrGet("start") or 1) if token.type == "ordered_list_open" else None
        items, i = [], 0
        while i < len(inner):
            end = _close(inner, i)
            body = inner[i + 1 : end]
            tight = any(t.type == "paragraph_open" and t.hidden for t in body)
            text = ("\n" if tight else "\n\n").join(self._blocks(body, True))
            marker = "- " if number is None else f"{number}. "
            items.append(marker + text.replace("\n", "\n" + " " * len(marker)))
            number = None if number is None else number + 1
            i = end + 1
        return "\n".join(items)

    # Inline

    def _inline(self, tokens: list[Token], start: bool = True) -> str:
        """Render inline tokens. `start` is true when the first one begins a line."""
        out: list[str] = []
        text = ""

        def flush():
            nonlocal text, start
            if start:
                text = text.lstrip()  # a space after <br> would hide the line start
            if text:
                out.append(_esc(text, start))
                text, start = "", False

        def add(markup: str):
            nonlocal start
            if not markup:  # a dropped image leaves the line as it was
                return
            flush()
            out.append(markup)
            start = markup.endswith("\n")

        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if kind in ("text", "text_special"):
                text += token.content
            elif kind == "softbreak":
                text += " "
            elif kind == "hardbreak":
                add(" \\\n")
            elif kind in ("em_open", "strong_open"):
                end = _close(tokens, i)
                flush()
                before = out[-1][-1:] if out else ""
                following = tokens[end + 1] if end + 1 < len(tokens) else None
                after = following.content[:1] if following and following.type == "text" else ""
                inner = self._inline(tokens[i + 1 : end], start=False)
                mark, name = ("_", "emph") if kind == "em_open" else ("*", "strong")
                if before.isalnum() or after.isalnum():  # Typst ignores _ and * inside a word
                    add(f"#{name}[{inner}];")
                else:
                    add(f"{mark}{inner}{mark}")
                i = end
            elif kind == "link_open":
                end = _close(tokens, i)  # the link text is kept, the target is not
                flush()
                out.append(self._inline(tokens[i + 1 : end], start=start))
                start = False
                i = end
            elif kind == "code_inline":
                add(f'#raw("{_str(token.content)}");')
            elif kind == "image":
                add(self._image(token.attrGet("src") or "", _plain(token) or token.content))
            elif kind == "html_inline":
                tag = token.content.lower()
                if tag.startswith("<br"):
                    add(" \\\n")
                elif tag.startswith("<img"):
                    images = _Html(token.content).images
                    add(self._image(*images[0]) if images else "")
            elif kind == "footnote_ref":
                add(f"#super[{token.meta['id'] + 1}];")
            i += 1
        flush()
        return "".join(out)

    # Images and tables

    def _image(self, ref: str, caption: str) -> str:
        if self.stock:
            usable = self._lookup(ref) and not (self.profile and self.profile.drop_images)
            return _STOCK_BOX if usable else ""
        found = self._file(ref)
        if found is None:
            return ""
        key, size = found
        caption = _words(caption)
        label = f", caption: [{_esc(caption, True)}]" if caption else ""
        box = self._box(size, caption)
        return f'#figure(image("{_str(key)}", {box}, fit: "contain"){label});'

    def _box(self, size: tuple[int, int] | None, caption: str) -> str:
        """Image size: natural (1 px is 1 pt), at most the body width, and short enough that the
        image and its caption fit on one page body."""
        s = self.settings
        page_w, page_h = self._page_size()
        body_w = page_w - 2 * s.margin
        body_h = page_h - 2 * s.margin - 22
        reserve = 0.0
        if caption:
            lines = math.ceil(len(caption) / max(1, int(body_w / (s.font_size * _GLYPH_EM))))
            reserve = (lines * s.line_height + _FIGURE_GAP_EM) * s.font_size
        max_h = max(body_h - reserve, body_h * _MIN_IMAGE_SHARE)
        if size is None:  # a vector image has no pixel size
            return f"width: 100%, height: {_pt(max_h)}"
        w, h = size
        scale = min(1.0, body_w / w, max_h / h)
        return f"width: {_pt(w * scale)}, height: {_pt(h * scale)}"

    def _lookup(self, ref: str) -> Path | None:
        try:
            path = (self.base / unquote(ref)).resolve()
        except (OSError, ValueError):
            return None
        usable = path.suffix.lower() in _IMAGE_SUFFIXES and path.is_relative_to(self.base)
        return path if usable and path.is_file() else None

    def _file(self, ref: str) -> tuple[str, tuple[int, int] | None] | None:
        """Put the image into `files`. Returns its name there and its pixel size (None for a
        vector image), or None to leave it out."""
        path = self._lookup(ref)
        if path is None:
            return None
        if path not in self._found:
            try:
                self._found[path] = self._load(path)
            except _BAD_IMAGE:
                self._found[path] = None
        return self._found[path]

    def _load(self, path: Path) -> tuple[str, tuple[int, int] | None] | None:
        key = path.relative_to(self.base).as_posix()
        if self.profile is None:
            return self._load_as_is(path, key)
        result = transform_image(path.read_bytes(), self.profile)
        if result is None:
            return None
        key = self._unique(key, result.ext)
        with Image.open(BytesIO(result.data)) as im:
            size = im.size
        self.files[key] = result.data
        return key, size

    def _load_as_is(self, path: Path, key: str) -> tuple[str, tuple[int, int] | None] | None:
        """Check an image that is passed on unchanged. Typst picks the decoder from the extension
        and refuses the whole page for a file it cannot read, so the name must match the format."""
        suffix = path.suffix.lower()
        if suffix == ".svg":
            root = ET.parse(path).getroot()
            if root.tag not in ("svg", _SVG_ROOT):
                return None
            key = self._unique(key, "svg")
            self.files[key] = path
            return key, None
        with Image.open(path) as im:
            im.load()
            size, ext = im.size, _FORMAT_SUFFIX.get(im.format or "")
        if ext is None:
            return None
        if ext == suffix or (ext == ".jpg" and suffix == ".jpeg"):
            key = self._unique(key, suffix[1:])  # a renamed file may have taken the name
            self.files[key] = path
            return key, size
        key = self._unique(key, ext[1:])  # for example a JPEG saved as .png
        self.files[key] = path.read_bytes()
        return key, size

    def _unique(self, key: str, ext: str) -> str:
        """`key` with its extension replaced by `ext`, made unique among the files."""
        stem = Path(key).with_suffix("").as_posix()
        name, n = f"{stem}.{ext}", 1
        while name in self.files:
            n += 1
            name = f"{stem}-{n}.{ext}"
        return name

    def _html(self, markup: str) -> str:
        html = _Html(markup)
        parts = []
        if html.rows:
            parts.append(self._table(html.rows))
        elif html.images:
            caption = html.caption or html.images[0][1]
            parts += [
                self._image(src, caption if n == 0 else alt)
                for n, (src, alt) in enumerate(html.images)
            ]
        text = _words(html.text)
        if text:
            parts.append(_esc(text, True))
        return "\n\n".join(part for part in parts if part)

    def _table(self, rows: list[list[_Cell]]) -> str:
        columns = max(sum(cell.colspan for cell in row) for row in rows)
        if columns == 0:
            return ""
        spanned = any(c.colspan > 1 or c.rowspan > 1 for row in rows for c in row)
        wide = DEVICES[self.device] is not None and columns >= _TWIN_MIN_COLUMNS
        if self._twin and (spanned or wide) and self._lookup(self._twin):
            figure = self._image(self._twin, "")
            if figure or (self.profile and self.profile.drop_images):
                return figure  # an unreadable twin falls back to the table
        lines = []
        for row in rows:
            cells = [self._cell(cell) for cell in row]
            if not any(c.rowspan > 1 for r in rows for c in r):
                cells += ["[]"] * (columns - sum(c.colspan for c in row))
            lines.append("  " + ", ".join(cells) + ",")
        return "#table(\n  columns: " + str(columns) + ",\n" + "\n".join(lines) + "\n)"

    def _cell(self, cell: _Cell) -> str:
        text = _esc(_words(cell.text), True)
        body = f"[#strong[{text}]]" if cell.header else f"[{text}]"
        args = [f"colspan: {cell.colspan}"] * (cell.colspan > 1)
        args += [f"rowspan: {cell.rowspan}"] * (cell.rowspan > 1)
        return f"table.cell({', '.join(args)}){body}" if args else body
