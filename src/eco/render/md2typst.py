"""Markdown to Typst: the source the preview renderer compiles.

The converter reads the book the way the EPUB builder does (same markdown-it parser) and writes
one `main.typ` plus the image files it refers to. It writes no files itself.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin

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
        self._keys: dict[Path, str | None] = {}  # source image -> key in `files`, None if left out
        self._twin = ""
        self._env: dict = {}

    def convert(self) -> str:
        body = "\n\n".join(self._blocks(_MD.parse(self.text, self._env)))
        return f"{self._preamble()}\n{body}\n"

    def _preamble(self) -> str:
        s = self.settings
        width, height = DEVICES[self.device] or (480, 800)
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
            "#show heading.where(level: 1): it => { pagebreak(weak: true); it }\n"
            "#show figure.caption: it => it.body\n"
        )

    # Blocks

    def _blocks(self, tokens: list[Token]) -> list[str]:
        out, i = [], 0
        while i < len(tokens):
            token = tokens[i]
            if token.type == "html_block":
                comment = token.content.strip()
                if m := _PAGE.fullmatch(comment):
                    out.append(
                        f"#context [#metadata((src: {m[1]}, page: here().page())) <srcpage>]"
                    )
                    i += 1
                    continue
                if m := _TWIN.fullmatch(comment):
                    self._twin = m[1]
                    i += 1
                    continue
            if token.nesting == 1:
                end = _close(tokens, i)
                text = self._container(token, tokens[i + 1 : end], tokens[i : end + 1])
                i = end + 1
            else:
                text = self._leaf(token)
                i += 1
            self._twin = ""
            if text:
                out.append(text)
        return out

    def _leaf(self, token: Token) -> str:
        if token.type in ("fence", "code_block"):
            return f'#raw(block: true, "{_str(token.content.rstrip(chr(10)))}")'
        if token.type == "hr":
            return "#line(length: 100%, stroke: 0.5pt)"
        if token.type == "html_block":
            return self._html(token.content)
        return ""

    def _container(self, token: Token, inner: list[Token], whole: list[Token]) -> str:
        kind = token.type
        if kind == "heading_open":
            return self._heading(int(token.tag[1]), inner[0])
        if kind == "paragraph_open":
            return self._inline(inner[0].children or [])
        if kind in ("bullet_list_open", "ordered_list_open"):
            return self._list(token, inner)
        if kind == "blockquote_open":
            body = "\n\n".join(self._blocks(inner))
            return f"#block(inset: (left: 1em), stroke: (left: 0.5pt))[\n{body}\n]" if body else ""
        if kind == "table_open":
            return self._html(_MD.renderer.render(whole, _MD.options, self._env))
        body = "\n\n".join(self._blocks(inner))
        if kind == "footnote_open":
            return f"#super[{token.meta['id'] + 1}]; {body}"
        return body  # footnote_block_open and anything else that only holds blocks

    def _heading(self, level: int, inline: Token) -> str:
        text = f"{'=' * level} {self._inline(inline.children or [], start=False)}"
        if level > 1:
            return text
        title = _str(_plain(inline) or self.title)
        marker = f'#context [#metadata((title: "{title}", page: here().page())) <chap>]'
        # The break is explicit so the marker lands on the chapter's own first page.
        return f"#pagebreak(weak: true)\n{marker}\n{text}"

    def _list(self, token: Token, inner: list[Token]) -> str:
        number = int(token.attrGet("start") or 1) if token.type == "ordered_list_open" else None
        items, i = [], 0
        while i < len(inner):
            end = _close(inner, i)
            body = inner[i + 1 : end]
            tight = any(t.type == "paragraph_open" and t.hidden for t in body)
            text = ("\n" if tight else "\n\n").join(self._blocks(body))
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
            if text:
                out.append(_esc(text, start))
                text, start = "", False

        def add(markup: str):
            nonlocal start
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
        key = self._file(ref)
        if key is None:
            return ""
        label = f", caption: [{_esc(_words(caption), True)}]" if _words(caption) else ""
        return f'#figure(image("{_str(key)}", width: 100%, fit: "contain"){label});'

    def _lookup(self, ref: str) -> Path | None:
        try:
            path = (self.base / unquote(ref)).resolve()
        except (OSError, ValueError):
            return None
        usable = path.suffix.lower() in _IMAGE_SUFFIXES and path.is_relative_to(self.base)
        return path if usable and path.is_file() else None

    def _file(self, ref: str) -> str | None:
        """Put the image into `files` and return its name there, or None to leave it out."""
        path = self._lookup(ref)
        if path is None:
            return None
        if path in self._keys:
            return self._keys[path]
        key: str | None = path.relative_to(self.base).as_posix()
        if self.profile is None:
            self.files[key] = path
        else:
            try:
                result = transform_image(path.read_bytes(), self.profile)
            except OSError:
                result = None
            if result is None:
                key = None
            else:
                stem = Path(key).with_suffix("")
                key, n = f"{stem.as_posix()}.{result.ext}", 1
                while key in self.files:
                    n += 1
                    key = f"{stem.as_posix()}-{n}.{result.ext}"
                self.files[key] = result.data
        self._keys[path] = key
        return key

    def _html(self, markup: str) -> str:
        html = _Html(markup)
        if html.rows:
            return self._table(html.rows)
        if html.images:
            caption = html.caption or html.images[0][1]
            figures = [
                self._image(src, caption if n == 0 else alt)
                for n, (src, alt) in enumerate(html.images)
            ]
            return "\n\n".join(f for f in figures if f)
        text = _words(html.text)
        return _esc(text, True) if text else ""

    def _table(self, rows: list[list[_Cell]]) -> str:
        columns = max(sum(cell.colspan for cell in row) for row in rows)
        if columns == 0:
            return ""
        spanned = any(c.colspan > 1 or c.rowspan > 1 for row in rows for c in row)
        wide = DEVICES[self.device] is not None and columns >= _TWIN_MIN_COLUMNS
        if self._twin and (spanned or wide) and self._lookup(self._twin):
            return self._image(self._twin, "")
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
