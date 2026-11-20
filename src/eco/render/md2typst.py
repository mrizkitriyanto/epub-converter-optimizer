"""Markdown to Typst: the source the preview renderer compiles.

The converter reads the book the way the EPUB builder does (same markdown-it parser) and writes
one `main.typ` plus the image files it refers to. It writes no files itself.
"""

import hashlib
import math
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import typst
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from PIL import Image

from eco.bookfolder import BookSource
from eco.epub.images import transform_image
from eco.options import DEVICES, ImageProfile
from eco.style import PageStyle, available_weights

VIEWS = ("crosspoint", "crossink", "stock", "xtc")

_MD = MarkdownIt("commonmark", {"html": True, "xhtmlOut": True}).enable("table")
_MD.use(footnote_plugin)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
_PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_TWIN = re.compile(r"<!--\s*table-image:\s*(.*?)\s*-->")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LANG = re.compile(r"[a-z]{2,3}")
_STOCK_BOX = "#rect(width: 100%, stroke: 1pt + gray)[Image not shown on stock firmware]"
_BIG_TABLE_BOX = "#rect(width: 100%, stroke: 1pt + gray)[Table too large to preview]"
_TWIN_MIN_COLUMNS = 5  # Xteink tables wider than 4 columns use their image twin
_MAX_COLSPAN = 1000  # browsers read a larger colspan as 1000
# Places (rows x columns) of the largest table the preview lays out. Typst pays for every place
# that holds a cell, an empty one too: 20,000 took 2-3 s and 250 MB on a laptop, and one colspan
# of 1,000 above 1,000 short rows (20 KB of HTML) took 94 s and 6 GB.
_MAX_TABLE_PLACES = 20_000
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
# The progress bar, in px. The line is thin, a chapter tick is taller and reaches past it on both
# sides, and the track (the part of the line that is not read yet) is light gray, a level XTH has.
_BAR_LINE = 2
_BAR_TICK = 6
_BAR_REACH = (_BAR_TICK - _BAR_LINE) // 2
_BAR_LINE_ROOM = _BAR_TICK - _BAR_REACH  # from the edge margin to the text, when there is a line
_BAR_TRACK = 170
_BAR_SEPARATOR = "  \u00b7  "
# The row of text is one string: the title, then the numbers that the style asks for, in this order.
# Each is a switch of the style and the Typst of its text (`p` of `n` pages, the chapter's pages).
_BAR_NUMBERS = (
    ("bar_page", 'str(p) + " / " + str(n)'),
    ("bar_book_percent", 'str(int(calc.round(100 * p / n))) + "%"'),
    ("bar_chapter_page", 'str(chap-page) + " / " + str(chap-pages)'),
    ("bar_chapter_percent", 'str(int(calc.round(100 * chap-page / chap-pages))) + "%"'),
)
# Numbers that do not fit the row are left out from the end, whole (half a number would read as
# another one). The first stays.
_BAR_FIT_NUMBERS = (
    "  while numbers.len() > 1 and measure(styled(numbers.join(sep))).width > row-w {",
    "    numbers = numbers.slice(0, -1)",
    "  }",
)
_BAR_CHAPTERS = (
    "  let chapters = query(<chap>).map(c => c.value)",
    "  let current = chapters.filter(c => c.page <= p)",
    "  let later = chapters.filter(c => c.page > p)",
    "  let chap-start = if current.len() > 0 { current.last().page } else { 1 }",
    "  let chap-pages = (if later.len() > 0 { later.first().page } else { n + 1 }) - chap-start",
    "  let chap-page = p - chap-start + 1",
)
# A title that is too long for the row is cut at a character: the longest start of it that fits
# with the numbers behind it (a binary search on the width that `measure` gives).
_BAR_TITLE = (
    '  let title = if current.len() > 0 { current.last().title } else { "" }',
    '  if title != "" {',
    '    let rest = if tail == "" { "" } else { sep + tail }',
    "    row = title + rest",
    "    if measure(styled(row)).width > row-w {",
    "      let cs = title.clusters()",
    "      let (lo, hi) = (0, cs.len())",
    "      while lo < hi {",
    "        let mid = calc.quo(lo + hi + 1, 2)",
    "        let fits = measure(styled(cs.slice(0, mid).join() + rest)).width <= row-w",
    "        if fits { lo = mid } else { hi = mid - 1 }",
    "      }",
    "      row = if lo > 0 { cs.slice(0, lo).join() + rest } else { tail }",
    "    }",
    "  }",
)
# What is left may still be wider than the row (a number alone, in a font with wide digits). It
# would break into a second line over the page, and half of a number reads as another one, so then
# nothing is drawn.
_BAR_FITS = '  if measure(styled(row)).width > row-w { row = "" }'

# Every image leaves its page and place in an `<imgbox>` marker, for `render_book` to query. The
# marker is made inside a box, which lies where the image does: in a figure whose caption is wider
# than the image, a position taken beside the box would be the start of the line that the image is
# centered in. An image of relative width (a vector image) measures 0 wide alone, so it is
# measured at the width of its container, which `layout` gives (a quote or a list takes some of
# the body's). `place` keeps that block out of the flow, so the image lies where it would without
# the rule.
_IMAGE_BOXES = (
    "#show image: it => box({\n"
    "  place(top + left, layout(size => {\n"
    "    let p = here().position()\n"
    "    let s = measure(width: size.width, it)\n"
    "    [#metadata((page: p.page, x: p.x.pt(), y: p.y.pt(), w: s.width.pt(), "
    "h: s.height.pt())) <imgbox>]\n"
    "  }))\n"
    "  it\n})"
)

# Typst markup characters, plus "~" (non-breaking space), "/" (term lists, comments) and the
# shorthands that change the characters of a text: "--", "---", "-?", a "-" before a number (a
# minus sign) and "..." (an ellipsis). A dot is escaped when two more follow it, so that no run of
# dots is left with three. A "-" or a "." that ends the text is escaped too: what is written next
# (the text of a link, which is escaped on its own) could join it. `_escape` keeps a "-" that
# only comes before a letter.
_SPECIAL = re.compile(r"[\\#$*_`<>@\[\]~/]|-(?=[\w?-]|\Z)|\.(?=\.\.|\Z)")
# Text that starts a line and would turn into a list, enum item or heading.
_LINE_START_ENUM = re.compile(r"^(\d+)\.")
_LINE_START_MARK = re.compile(r"^[-+=]")
_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def to_typst(
    src: BookSource,
    *,
    device: str,
    style: PageStyle,
    view: str,
    image_profile: ImageProfile | None = None,
    font_extra_dirs: Sequence[Path] = (),
) -> dict[str, bytes | Path]:
    """Return typst-py's multi-file input: `main.typ` plus every image the source refers to."""
    return _to_typst(src, device, style, view, image_profile, font_extra_dirs=font_extra_dirs)


def _to_typst(
    src: BookSource,
    device: str,
    style: PageStyle,
    view: str,
    image_profile: ImageProfile | None,
    *,
    defer_images: bool = False,
    selected_images: set[Path] | None = None,
    font_extra_dirs: Sequence[Path] = (),
) -> dict[str, bytes | Path]:
    if device not in DEVICES:
        raise ValueError(f"unknown device: {device!r}")
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view!r}")
    converter = _Converter(
        src,
        device,
        style,
        view,
        image_profile,
        defer_images=defer_images,
        selected_images=selected_images,
        font_extra_dirs=font_extra_dirs,
    )
    return {"main.typ": converter.convert().encode(), **converter.files}


def _escape(found: re.Match) -> str:
    """Escape a special character. A "-" counts only at the end of the text, or before another
    "-", "?" or a number. Any number: Typst makes a minus sign of a hyphen before a superscript or
    an Arabic-Indic digit too, and `isnumeric` knows those."""
    char = found[0]
    if char == "-":
        following = found.string[found.end() : found.end() + 1]  # "" at the end of the text
        if following and following not in "-?" and not following.isnumeric():
            return char
    return "\\" + char


def _esc(text: str, line_start: bool = False) -> str:
    """Escape text for Typst markup. `line_start` is true when the text begins a line."""
    text = _SPECIAL.sub(_escape, text)
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


# What Typst says of an SVG, by the hash of its bytes. Typst refuses the whole document for an SVG
# whose size or contents it cannot read, however well formed the XML is, so each one is compiled
# alone first (without an image profile no other step reads it).
_SVG_VERDICTS: dict[str, bool] = {}
_SVG_PROBE = (
    "#set page(width: 10pt, height: 10pt, margin: 0pt)\n"
    '#image("image.svg", width: 10pt, height: 10pt)\n'
)


def _typst_reads_svg(data: bytes) -> bool:
    digest = hashlib.sha256(data).hexdigest()
    if digest not in _SVG_VERDICTS:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp)
            (folder / "image.svg").write_bytes(data)
            (folder / "main.typ").write_text(_SVG_PROBE)
            try:
                typst.compile(
                    folder / "main.typ", root=str(folder), format="png", ignore_system_fonts=True
                )
                _SVG_VERDICTS[digest] = True
            except typst.TypstError:
                _SVG_VERDICTS[digest] = False
    return _SVG_VERDICTS[digest]


def _check_pixels(im: Image.Image) -> None:
    """Raise DecompressionBombError for an image of more than `Image.MAX_IMAGE_PIXELS` pixels.

    PIL itself refuses only an image of more than twice that and warns for the ones between, then
    decodes them whole. A small file can hold such a raster, and a preview must not decode one.
    """
    limit = Image.MAX_IMAGE_PIXELS
    if limit and im.width * im.height > limit:
        raise Image.DecompressionBombError(f"Image of {im.width}x{im.height} pixels is too large")


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
    """A colspan or rowspan as written: a whole number in ASCII digits, else 1. A number too long
    to read is 10**9, more than any limit it meets."""
    digits = (value or "").strip()
    if not (digits.isascii() and digits.isdecimal()):
        return 1
    digits = digits.lstrip("0") or "0"
    return int(digits) if len(digits) < 10 else 10**9


def _layout(rows: list[list[_Cell]]) -> tuple[int, list[int]] | None:
    """Place the cells the way a browser does: row by row, each in the first column that no cell
    above takes with its rowspan. A rowspan is cut to the rows that are left, and 0 means all of
    them; a colspan stops at a column that a cell above takes. Returns the number of columns and,
    for each row, the places it leaves empty, which the table fills so that Typst puts each cell
    where a browser does. None for a table of more than _MAX_TABLE_PLACES places."""
    until: list[int] = []  # for each column, the first row that it is free in again
    taken = []
    for r, row in enumerate(rows):
        left = len(rows) - r
        col = 0
        for cell in row:
            if not 0 < cell.rowspan <= left:
                cell.rowspan = left
            while col < len(until) and until[col] > r:
                col += 1
            end = col + cell.colspan
            # a browser lets a colspan overlap a rowspan from above; Typst refuses the table
            end = next((c for c in range(col, min(end, len(until))) if until[c] > r), end)
            cell.colspan = end - col
            if end > len(until):
                if end * len(rows) > _MAX_TABLE_PLACES:
                    return None
                until += [0] * (end - len(until))
            until[col:end] = [r + cell.rowspan] * cell.colspan
            col = end
        taken.append(sum(free > r for free in until))
    return len(until), [len(until) - n for n in taken]


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
            colspan = min(max(_span(attr.get("colspan")), 1), _MAX_COLSPAN)
            self._cell = _Cell(tag == "th", colspan, _span(attr.get("rowspan")))
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


def _bar_area(style: PageStyle) -> int:
    """The px that the progress bar takes from the page, on its side: its text and an edge margin
    on each side of the text. With a line, the side that the line is on takes `_BAR_LINE_ROOM` px
    where the edge margin is less (M3-R11: the area holds all that the bar draws). Nothing when
    the bar is off."""
    if style.bar_position == "off":
        return 0
    edge = style.bar_edge_margin
    line_side = max(edge, _BAR_LINE_ROOM) if style.bar_line else edge
    return style.bar_font_size + edge + line_side


def _bar(style: PageStyle, width: int, height: int) -> tuple[str, str]:
    """The progress bar of a page `width` by `height` px: the lines that come before `#set page`,
    and the arguments of `#set page` that hang the bar in the header or the footer. Both are empty
    when the bar is off.

    The bar has `_bar_area` px at the edge of the page, and the margin lies between it and the
    text. From the edge inwards: `bar_edge_margin` px, the progress line (its ticks reach past it
    on both sides), and the row of text, which starts at the edge margin when there is no line.
    The header starts at the top edge of the page and the footer at the bottom edge of the text,
    so `place` puts each part where it goes.
    """
    if style.bar_position == "off":
        return "", ""
    top = style.bar_position == "top"
    edge, side, size = style.bar_edge_margin, style.bar_side_margin, style.bar_font_size
    origin_x = style.margin_x
    origin_y = 0 if top else height - style.margin_y - _bar_area(style)
    row_w = width - 2 * side
    line_x, line_w = (0, width) if style.bar_full_width else (side, row_w)

    def put(dx: str, from_edge: int, extent: int, part: str) -> str:
        """`part`, `extent` px tall, put `from_edge` px from the edge of the page."""
        y = from_edge if top else height - from_edge - extent
        return f"place(top + left, dx: {dx}, dy: {y - origin_y}pt, {part})"

    numbers = [code for switch, code in _BAR_NUMBERS if getattr(style, switch)]
    marks = style.bar_line and style.bar_chapter_marks
    chapters = style.bar_chapter_title or style.bar_chapter_page or style.bar_chapter_percent
    text_from_edge = edge + _BAR_LINE_ROOM if style.bar_line else edge
    row = f"box(width: row-w, height: {size}pt, align(horizon + left, styled(row)))"
    tail = ['  let tail = ""']
    if numbers:
        tail = [f"  let numbers = ({', '.join(numbers)},)"]
        tail += _BAR_FIT_NUMBERS if len(numbers) > 1 else ()
        tail.append("  let tail = numbers.join(sep)")
    lines = [
        "#let eco-bar = context {",
        "  let n = counter(page).final().first()",
        "  let p = counter(page).get().first()",
        f"  let row-w = {row_w}pt",
        f"  let styled(body) = text(size: {size}pt, body)",
        f'  let sep = "{_BAR_SEPARATOR}"',
        *(_BAR_CHAPTERS if chapters or marks else ()),
        *tail,
        "  let row = tail",
        *(_BAR_TITLE if style.bar_chapter_title else ()),
        _BAR_FITS,
        "  " + put(f"{side - origin_x}pt", text_from_edge, size, row),
    ]
    if style.bar_line:
        thin = f"height: {_BAR_LINE}pt, stroke: none"
        track = f"rect(width: {line_w}pt, {thin}, fill: luma({_BAR_TRACK}))"
        read = f"rect(width: calc.round({line_w} * p / n) * 1pt, {thin}, fill: black)"
        lines += [
            "  " + put(f"{line_x - origin_x}pt", edge, _BAR_LINE, part) for part in (track, read)
        ]
    if marks:  # a tick is 2 px wide, with its middle at the start of its chapter
        dx = f"{line_x - origin_x - 1}pt + calc.round({line_w} * (c.page - 1) / n) * 1pt"
        rect = f"rect(width: 2pt, height: {_BAR_TICK}pt, fill: black, stroke: none)"
        tick = put(dx, edge - _BAR_REACH, _BAR_TICK, rect)
        lines += ["  for c in chapters {", f"    if c.page > 1 {{ {tick} }}", "  }"]
    lines.append("}")
    argument, spacing = ("header", "header-ascent") if top else ("footer", "footer-descent")
    return "\n".join(lines) + "\n", f",\n  {spacing}: 0pt,\n  {argument}: eco-bar"


class _Converter:
    def __init__(
        self,
        src: BookSource,
        device: str,
        style: PageStyle,
        view: str,
        profile: ImageProfile | None,
        *,
        defer_images: bool = False,
        selected_images: set[Path] | None = None,
        font_extra_dirs: Sequence[Path] = (),
    ):
        self.meta = src.meta
        self.title = src.meta["title"]
        self.text = _CONTROL.sub("", src.markdown)
        self.base = src.base_dir.resolve()
        self.device = device
        self.style = style
        self.view = view
        self.font_extra_dirs = font_extra_dirs
        self.stock = view == "stock"
        self.profile = profile
        self.defer_images = defer_images
        self.selected_images = selected_images
        self.bar_area = _bar_area(style)
        self.files: dict[str, bytes | Path] = {}
        self._found: dict[Path, tuple[str, tuple[int, int] | None] | None] = {}  # None: left out
        self._twin = ""
        self._lead: list[str] = []  # page markers that wait for the chapter heading after them
        self._env: dict = {}

    def convert(self) -> str:
        body = "\n\n".join(self._blocks(_MD.parse(self.text, self._env)))
        return f"{self._preamble()}\n{body}\n"

    def _page_size(self) -> tuple[int, int]:
        """The page Typst lays out: the device's screen, on its side for 90 and 270 degrees.
        `render_book` turns the pages back to the screen."""
        width, height = DEVICES[self.device] or (480, 800)
        return (height, width) if self.style.orientation in (90, 270) else (width, height)

    def _lang(self) -> str:
        if self.style.lang != "auto":
            return self.style.lang
        language = _words(self.meta.get("language") or "").lower().replace("_", "-")
        lang = language.split("-")[0]
        return lang if _LANG.fullmatch(lang) else "en"

    def _preamble(self) -> str:
        """The lines before the book. There is no blank line in them: `render_chapter` cuts at the
        first one."""
        s = self.style
        width, height = self._page_size()
        top = s.margin_y + self.bar_area * (s.bar_position == "top")
        bottom = s.margin_y + self.bar_area * (s.bar_position == "bottom")
        bar, bar_arguments = _bar(s, width, height)
        focus = ""
        if s.focus_mode:
            weights = available_weights(s.font, self.font_extra_dirs)
            heavier = [weight for weight in weights if weight > s.font_weight]
            if heavier:
                target = next(
                    (weight for weight in heavier if weight >= s.font_weight + 300), heavier[-1]
                )
                ratio = {"low": 0.3, "medium": 0.5, "high": 0.7}[s.focus_strength]
                focus = (
                    "#let focus(body) = {\n"
                    '  show regex("[\\\\p{Latin}\\\\p{Greek}\\\\p{Cyrillic}][\\\\p{Latin}\\\\p{Greek}\\\\p{Cyrillic}\\\\p{M}]*"): it => {\n'
                    f"    let c = it.text.clusters(); let n = if c.len() == 1 {{ 1 }} else {{ calc.min(c.len() - 1, calc.max(1, calc.ceil(c.len() * {ratio}))) }}\n"
                    f"    text(weight: {target}, c.slice(0, n).join()) + c.slice(n).join()\n"
                    "  }; body\n}\n"
                )
        return (
            f"{bar}"
            f"#set page(width: {width}pt, height: {height}pt, "
            f"margin: (x: {s.margin_x}pt, top: {top}pt, bottom: {bottom}pt){bar_arguments})\n"
            f'#set text(font: "{_str(s.font)}", weight: {int(s.font_weight)}, '
            f'size: {s.font_size}pt, lang: "{_str(self._lang())}", '
            f"hyphenate: {str(s.hyphenate).lower()})\n"
            f"#set par(justify: {str(s.align == 'justify').lower()}, "
            f"leading: {(s.line_height - 100) / 100:g}em"
            f"{f', spacing: {s.paragraph_spacing / 100:g}em' if s.paragraph_spacing != 120 else ''}"
            f"{f', first-line-indent: {s.first_line_indent / 100:g}em' if s.first_line_indent else ''})\n"
            "#set smartquote(enabled: false)\n"
            '#show raw: set text(font: "DejaVu Sans Mono", size: 0.62em)\n'
            f"{self._raw_wrap()}\n"
            f"{focus}"
            "#show heading.where(level: 1): it => { pagebreak(weak: true); it }\n"
            "#show figure.caption: it => it.body\n"
            f"{_IMAGE_BOXES}\n"
        )

    def _raw_wrap(self) -> str:
        """A raw line that is wider than the page runs past the edge. Zero-width spaces between the
        characters of any run of `fit` characters or more let it wrap at the page edge."""
        width = self._page_size()[0] - 2 * self.style.margin_x
        fit = max(8, int(width / (_MONO_EM * _RAW_EM * self.style.font_size)))
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
            text = self._inline(inner[0].children or [], focus=self.style.focus_mode)
            return f"#align(center)[{text}]" if self.style.align == "center" else text
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

    def _inline(self, tokens: list[Token], start: bool = True, focus: bool = False) -> str:
        """Render inline tokens. `start` is true when the first one begins a line."""
        out: list[str] = []
        text = ""

        def flush():
            nonlocal text, start
            if start:
                text = text.lstrip()  # a space after <br> would hide the line start
            if text:
                shown = _esc(text, start)
                out.append(f"#focus[{shown}]" if focus else shown)
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
                inner = self._inline(tokens[i + 1 : end], start=False, focus=focus)
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
        s = self.style
        page_w, page_h = self._page_size()
        body_w = page_w - 2 * s.margin_x
        body_h = page_h - 2 * s.margin_y - self.bar_area
        reserve = 0.0
        if caption:
            lines = math.ceil(len(caption) / max(1, int(body_w / (s.font_size * _GLYPH_EM))))
            reserve = (lines * s.line_height / 100 + _FIGURE_GAP_EM) * s.font_size
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
        if path is None or (self.selected_images is not None and path not in self.selected_images):
            return None
        if path not in self._found:
            if self.defer_images:
                key = path.relative_to(self.base).as_posix()
                self.files[key] = path
                self._found[path] = (key, None)
            else:
                try:
                    self._found[path] = self._load(path)
                except _BAD_IMAGE:
                    self._found[path] = None
        return self._found[path]

    def _load(self, path: Path) -> tuple[str, tuple[int, int] | None] | None:
        key = path.relative_to(self.base).as_posix()
        if self.profile is None:
            return self._load_as_is(path, key)
        data = path.read_bytes()
        with Image.open(BytesIO(data)) as im:
            _check_pixels(im)
        result = transform_image(data, self.profile)
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
            if root.tag not in ("svg", _SVG_ROOT) or not _typst_reads_svg(path.read_bytes()):
                return None
            key = self._unique(key, "svg")
            self.files[key] = path
            return key, None
        with Image.open(path) as im:
            _check_pixels(im)
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
        layout = _layout(rows)
        columns, empty = layout or (0, [])
        if layout and columns == 0:
            return ""
        spanned = any(c.colspan > 1 or c.rowspan > 1 for row in rows for c in row)
        wide = DEVICES[self.device] is not None and columns >= _TWIN_MIN_COLUMNS
        if self._twin and (spanned or wide or not layout) and self._lookup(self._twin):
            figure = self._image(self._twin, "")
            if figure or (self.profile and self.profile.drop_images):
                return figure  # an unreadable twin falls back to the table
        if not layout:
            return _BIG_TABLE_BOX
        lines = []
        for row, places in zip(rows, empty, strict=True):
            cells = [self._cell(cell) for cell in row] + ["[]"] * places
            lines.append("  " + ", ".join(cells) + ",")
        return "#table(\n  columns: " + str(columns) + ",\n" + "\n".join(lines) + "\n)"

    def _cell(self, cell: _Cell) -> str:
        text = _esc(_words(cell.text), True)
        body = f"[#strong[{text}]]" if cell.header else f"[{text}]"
        args = [f"colspan: {cell.colspan}"] * (cell.colspan > 1)
        args += [f"rowspan: {cell.rowspan}"] * (cell.rowspan > 1)
        return f"table.cell({', '.join(args)}){body}" if args else body
