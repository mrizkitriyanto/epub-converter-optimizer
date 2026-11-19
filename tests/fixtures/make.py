"""Synthetic PDFs compiled with Typst and synthetic EPUBs written with zipfile. Every PDF bbox is
in PDF points, top-left origin, relative to the page's CropBox (the same convention as the
pipeline's blocks)."""

import base64
import random
import zipfile
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import typst
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw

Bbox = tuple[float, float, float, float]

PAGE = "#set page(width: 612pt, height: 792pt, margin: 0pt)\n"
SERIF = '#set text(font: "Libertinus Serif", size: 11pt)\n'
MONO = '#show raw: set text(font: "DejaVu Sans Mono", size: 10pt)\n'
CODE_LINES = [
    "2000F3B8 PrintReportRows",
    "    test eax",
    "    jnz exit",
    "    call Report_flush_all_buffers",
]


def _compile(source: str, **kwargs) -> bytes:
    return typst.compile(source.encode(), ignore_system_fonts=True, **kwargs)


def _png(source: str, ppi: int) -> Image.Image:
    """Render a one-page source (typst returns bare bytes for a single page)."""
    return Image.open(BytesIO(_compile(source, format="png", ppi=ppi))).convert("RGB")


def _write(directory: Path, name: str, data: bytes) -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


def two_column_pdf(directory: Path) -> tuple[Path, list[str]]:
    # Spike layout: the left column holds Abstract, the abstract and a long introduction; the
    # right column starts with a 120 pt picture placeholder, so its text begins beside the left
    # intro and a plain top-to-bottom sort mixes the columns.
    abstract = "This abstract paragraph summarises the fixture in a few short sentences. " * 3
    intro = " ".join(
        f"Introduction sentence number {n} fills the left column." for n in range(1, 31)
    )
    right = [
        "Right column first paragraph after the figure. " * 6,
        "Right column second paragraph with more text. " * 6,
    ]
    abstract, intro = abstract.strip(), intro.strip()
    right = [r.strip() for r in right]
    source = (
        PAGE
        + SERIF
        + "#pad(54pt)[\n"
        + '#align(center)[#text(size: 20pt, weight: "bold")[Deep Fixture Paper]]\n\n'
        + "#align(center)[Ada Lovelace and Alan Turing]\n\n"
        + "#grid(columns: (1fr, 1fr), column-gutter: 18pt,\n"
        + '  [#text(weight: "bold")[Abstract]\n\n'
        + f'  {abstract}\n\n  #text(weight: "bold")[1\\. Introduction]\n\n  {intro}],\n'
        + "  [#rect(width: 100%, height: 120pt)\n\n"
        + f"  {right[0]}\n\n  {right[1]}],\n)\n]\n"
    )
    texts = [
        "Deep Fixture Paper",
        "Ada Lovelace and Alan Turing",
        "Abstract",
        abstract,
        "1. Introduction",
        intro,
        *right,
    ]
    return _write(directory, "two_column.pdf", _compile(source)), texts


def code_pdf(
    directory: Path, crop_offset: tuple[float, float] = (54.0, 63.0)
) -> tuple[Path, list[str], Bbox]:
    code = "\\n".join(CODE_LINES)
    source = (
        PAGE
        + SERIF
        + MONO
        + "#place(top + left, dx: 72pt, dy: 100pt, box(width: 400pt)[This paragraph explains the "
        + "disassembly listing below. It is ordinary prose set in the serif font.])\n"
        + f'#place(top + left, dx: 72pt, dy: 200pt, raw("{code}", block: true))\n'
    )
    left, top = crop_offset
    # Open from memory: saving over a file pdfium still reads lazily corrupts the text layer.
    pdf = pdfium.PdfDocument(_compile(source))
    pdf[0].set_cropbox(left, 792 - top - 666, left + 504, 792 - top)
    path = directory / "code.pdf"
    pdf.save(path)
    # The glyph boxes of the four lines measure 198 x 52.4 pt (monospace 10 pt, widest line has 33
    # chars); the bbox pads that by 2 pt and moves it into CropBox-relative coordinates.
    bbox = (72 - left - 2, 200 - top - 2, 72 - left + 200, 200 - top + 55)
    return path, CODE_LINES, bbox


def formula_pdf(directory: Path) -> tuple[Path, Bbox]:
    source = PAGE + SERIF + "#place(top + left, dx: 100pt, dy: 300pt, block(width: 200pt)[\n"
    source += "$ y = F(x, {W_i}) + x $])\n"
    path = _write(directory, "formula.pdf", _compile(source))
    # The page holds only the equation, so its ink box is the formula bbox (render at 4x).
    x0, y0, x1, y1 = ImageChops.invert(_png(source, 288).convert("L")).getbbox()
    return path, (x0 / 4 - 1, y0 / 4 - 1, x1 / 4 + 1, y1 / 4 + 1)


def blank_middle_pdf(directory: Path) -> Path:
    source = PAGE + SERIF + "#pad(54pt)[First page text.]\n#pagebreak()\n#pagebreak()\n"
    source += "#pad(54pt)[Third page text.]\n"
    return _write(directory, "blank_middle.pdf", _compile(source))


def hyphen_pdf(directory: Path) -> Path:
    # Forced line breaks make the dehyphenation case deterministic: "seper–" ends a line.
    source = PAGE + SERIF + "#pad(54pt)[#box(width: 160pt)[Kata itu terlihat seper–\\\n"
    source += "tinya benar. Kata sepertinya muncul lagi di sini.]]\n"
    return _write(directory, "hyphen.pdf", _compile(source))


def scanned_pdf(directory: Path) -> tuple[Path, str]:
    text = "Scanned page with no text layer."
    source = PAGE + SERIF + f"#pad(54pt)[{text}]\n"
    path = directory / "scanned.pdf"
    _png(source, 200).save(path, resolution=200)
    return path, text


def tall_pdf(directory: Path) -> Path:
    source = "#set page(width: 400pt, height: 2400pt, margin: 20pt)\n" + SERIF + "#lorem(900)\n"
    return _write(directory, "tall.pdf", _compile(source))


def photo_pdf(directory: Path) -> tuple[Path, Bbox]:
    """A full-page noise picture with no text layer. The bbox lies inside it."""
    rng = random.Random(5)
    noise = Image.frombytes("RGB", (153, 198), rng.randbytes(153 * 198 * 3))
    path = directory / "photo.pdf"
    noise.resize((612, 792), Image.Resampling.BICUBIC).save(path, resolution=72)
    return path, (100.0, 100.0, 300.0, 250.0)


def shapes_pdf(directory: Path) -> tuple[Path, Bbox]:
    """Two flat-colour rectangles at whole points, so a crop has only a few colours."""
    source = PAGE + "".join(
        f'#place(top + left, dx: {x}pt, dy: {y}pt, rect(width: 100pt, height: 60pt, fill: rgb("{c}")))\n'
        for x, y, c in ((100, 100, "#ff0000"), (220, 100, "#0000ff"))
    )
    return _write(directory, "shapes.pdf", _compile(source)), (100.0, 100.0, 320.0, 160.0)


def contents_pdf(directory: Path) -> Path:
    """Three pages: a contents page (full-width part titles, two columns of entries with dot
    leaders and print page numbers), a page of text, and an index in two columns."""

    def at(x: int, y: int, text: str, size: int = 11) -> str:
        return f"#place(top + left, dx: {x}pt, dy: {y}pt)[#text(size: {size}pt)[{text}]]\n"

    contents = at(72, 50, "Contents", 18) + at(
        72, 100, "Part One: Getting Ready for the Long Walk", 16
    )
    for n, (left, right) in enumerate(
        [("Alpha steps", "Delta notes"), ("Beta steps", "Epsilon notes"), ("Preface", "Zeta notes")]
    ):
        y = 130 + 16 * n
        number = "xi" if left == "Preface" else str(3 + n)
        contents += at(72, y, f"{left} . . . . . . {number}") + at(330, y, f"{right} {20 + n}")
    contents += at(72, 190, "Part Two: Coming Home Again Much Later", 16)
    contents += at(72, 220, "Eta work 31") + at(330, 220, "Iota work 35")
    index = at(72, 50, "Index", 18)
    for n, (left, right) in enumerate([("apple 12, 14", "banana 7"), ("pie 15", "cherry 3, 9")]):
        index += at(72, 100 + 16 * n, left) + at(330, 100 + 16 * n, right)
    source = PAGE + SERIF + contents + "#pagebreak()\n" + at(72, 72, "A page of ordinary text.")
    source += "#pagebreak()\n" + index
    return _write(directory, "contents.pdf", _compile(source))


def contents_layouts_pdf(directory: Path) -> Path:
    """Four pages with the layouts `contents_pdf` does not have. Page 1: one column of contents
    whose page numbers are runs of their own at the right margin, with lines that end in a word
    that looks like a number. Page 2: two columns whose page numbers are runs of their own at the
    right edge of each column (280 and 540 pt), and a short part title centred over the gutter.
    Page 3: text. Page 4: an index whose commas are runs of their own. Text is set as Typst
    strings, so "..." stays three dots."""

    def at(x: float, y: float, text: str, size: int = 11) -> str:
        return f'#place(top + left, dx: {x}pt, dy: {y}pt)[#text(size: {size}pt, "{text}")]\n'

    def ending_at(x: float, y: float, text: str) -> str:
        return f'#place(top + right, dx: {x - 612}pt, dy: {y}pt)[#text(size: 11pt, "{text}")]\n'

    one = at(72, 100, "Part One: Basics of the work", 14)
    for n, (x, title, number) in enumerate(
        [
            (72, "Preface", "xi"),
            (72, "Hunting on Windows 10", "45"),
            (72, "Lab mix", "50"),
            (72, "Editing with vi", ""),  # the first line of an entry of two lines
            (84, "and other tools", "52"),
            (72, "What next...", ""),
            (72, "Chapter Two Is A Long Title That Runs Across", "60"),
            (72, "Chapter 3 Basics ........ 117", ""),  # the number in the run, after a leader
        ]
    ):
        one += at(x, 130 + 16 * n, title) + (ending_at(540, 130 + 16 * n, number) if number else "")
    two = at(72, 100, "Part One: Getting Ready for the Long Walk", 16)
    rows = [
        (130, ("Alpha steps", "3"), ("Delta notes", "20")),
        (146, ("Beta steps", "5"), ("Epsilon notes", "22")),
        (162, ("Gamma steps", "8"), ("Zeta notes", "25")),
        (220, ("Eta work", "31"), ("Iota work", "35")),
        (236, ("Theta work", "33"), ("Kappa work", "37")),
    ]
    for y, (left, left_number), (right, right_number) in rows:
        two += at(72, y, left) + ending_at(280, y, left_number)
        two += at(330, y, right) + ending_at(540, y, right_number)
    two += '#place(top + center, dy: 190pt)[#text(size: 14pt, "Part Two")]\n'
    # the comma touches "116", and its glyph box sits 6 pt below the top of the line
    index = at(72, 50, "Index", 18) + at(72, 100, "protecting 116") + at(136.3, 100, ",")
    index += at(141, 100, "117") + at(72, 114, "pyramid 3") + at(80, 128, "of pain 5")
    source = PAGE + SERIF + one + "#pagebreak()\n" + two + "#pagebreak()\n"
    source += at(72, 72, "A page of ordinary text.") + "#pagebreak()\n" + index
    return _write(directory, "contents_layouts.pdf", _compile(source))


LABELS = ["Introduction", "Methods", "Results", "Discussion", "Summary"]


def column_layouts_pdf(directory: Path) -> Path:
    """Eleven pages of layouts that decide between one column and two, with no full-width line.
    Contents (pages 1-5): (1) a short last column, two lines on the right beside five on the
    left, page numbers as runs at the right edge of each column (280 and 540 pt); (2) a right
    column of one line; (3) "Chapter n" labels at 72 pt beside short titles at 140 pt, page
    numbers at the right margin; (4) the same labels and titles without page numbers; (5) two
    columns without page numbers, with an italic run that starts past the middle of the left
    column after other text, and a code run after other text in the right column. Page 6: text.
    Index (pages 7-10): (7) six long entries on the left and three short ones on the right;
    (8) an italic "see also" past the middle of the left column; (9) three columns, at 72, 250
    and 428 pt; (10) a right column of one line; (11) a word broken at a line end."""

    def at(x: float, y: float, text: str, size: int = 11, style: str = "") -> str:
        look = {"italic": ', style: "italic"', "code": ', font: "DejaVu Sans Mono"', "": ""}
        return (
            f"#place(top + left, dx: {x}pt, dy: {y}pt)"
            f'[#text(size: {size}pt{look[style]}, "{text}")]\n'
        )

    def ending_at(x: float, y: float, text: str) -> str:
        return f'#place(top + right, dx: {x - 612}pt, dy: {y}pt)[#text(size: 11pt, "{text}")]\n'

    def columns(lefts: list[tuple[str, str]], rights: list[tuple[str, str]]) -> str:
        page = ""
        for n, (title, number) in enumerate(lefts):
            page += at(72, 100 + 16 * n, title) + ending_at(280, 100 + 16 * n, number)
        for n, (title, number) in enumerate(rights):
            page += at(330, 100 + 16 * n, title) + ending_at(540, 100 + 16 * n, number)
        return page

    left = [("Alpha steps", "3"), ("Beta steps", "5"), ("Gamma steps", "8"), ("Delta steps", "9")]
    pages = [
        columns([*left, ("Epsilon steps", "11")], [("Zeta notes", "20"), ("Eta notes", "22")]),
        columns(left, [("Zeta notes", "20")]),
        "".join(
            at(72, 100 + 16 * n, f"Chapter {n + 1}")
            + at(140, 100 + 16 * n, title)
            + ending_at(540, 100 + 16 * n, str(5 + 10 * n))
            for n, title in enumerate(LABELS)
        ),
        "".join(
            at(72, 100 + 16 * n, f"Chapter {n + 1}") + at(140, 100 + 16 * n, title)
            for n, title in enumerate(LABELS)
        ),
        "".join(
            at(72, 100 + 16 * n, a) + at(330, 100 + 16 * n, b)
            for n, (a, b) in enumerate(
                [
                    ("Alpha steps", "Eps notes"),
                    ("Beta steps", "Zeta notes"),
                    ("Detecting lateral movement with", "Logs from"),
                    ("Gamma steps", "Theta notes"),
                    ("Delta steps", "Iota notes"),
                ]
            )
        )
        + at(228, 132, "PsExec", style="italic")
        + at(380, 132, "auditd", size=10, style="code"),
        at(72, 72, "A page of ordinary text."),
    ]
    index = [
        ("web shells, detecting 101, 140", "YARA rules 150"),
        ("Windows Event Forwarding 88", "zero trust 12"),
        ("Windows Management Instrumentation 63, 70", "Zeek 98"),
        ("workstation hunting 77", ""),
        ("WMI persistence 71, 72", ""),
        ("XDR platforms 30", ""),
    ]
    pages.append(
        "".join(
            at(72, 100 + 13 * n, a, 10) + (at(330, 100 + 13 * n, b, 10) if b else "")
            for n, (a, b) in enumerate(index)
        )
    )
    pairs = [("apple 12", "kiwi 3"), ("banana 7, 9,", "lemon 4"), ("fruit 2", "mango 8")]
    pages.append(
        "".join(
            at(72, 100 + 14 * n, a) + at(330, 100 + 14 * n, b) for n, (a, b) in enumerate(pairs)
        )
        + at(205, 114, "see also", style="italic")
        + at(250, 114, "fruit")
    )
    trees = [(72, ["acorn", "birch", "cedar"]), (250, ["dogwood", "elm", "fir"])]
    trees.append((428, ["ginkgo", "hazel", "ivy"]))
    pages.append(
        "".join(
            at(x, 100 + 14 * n, f"{word} {n + 1}")
            for x, words in trees
            for n, word in enumerate(words)
        )
    )
    pages.append(
        "".join(at(72, 100 + 14 * n, f"{w} {n + 2}") for n, w in enumerate(["oak", "pine", "yew"]))
        + at(330, 100, "zelkova 40")
    )
    # (11) a word broken at a line end: PDFium marks that hyphen as a character of its own
    pages.append(
        at(72, 100, "anomaly detec-") + at(72, 114, "tion 40") + at(72, 128, "audit logs 9")
    )
    source = PAGE + SERIF + "#pagebreak()\n".join(pages)
    return _write(directory, "column_layouts.pdf", _compile(source))


def picture_text_pdf(directory: Path) -> Path:
    """A page with a text layer and two raster pictures of text, each 200 x 100 pt: the first at
    (100, 150), with a caption under it in the text layer; the second at (100, 320), with a label
    of the text layer printed over it."""
    words = "#set page(width: 200pt, height: 100pt, margin: 8pt)\n" + SERIF
    words += "Pictured words\n\ninside a figure"
    _png(words, 150).save(directory / "pictured.png")
    place = "#place(top + left, dx: {}pt, dy: {}pt)[{}]\n"
    source = PAGE + SERIF + place.format(72, 60, "Ordinary text that the text layer holds.")
    source += place.format(100, 150, '#image("pictured.png", width: 200pt)')
    source += place.format(100, 260, "Figure 1 - a caption in the text layer")
    source += place.format(100, 320, '#image("pictured.png", width: 200pt)')
    source += place.format(110, 330, "Overlay label")
    typ = directory / "picture_text.typ"
    typ.write_text(source, encoding="utf-8")
    data = typst.compile(str(typ), root=str(directory), ignore_system_fonts=True)
    return _write(directory, "picture_text.pdf", data)


def form_image_pdf(path: Path, forms: list[tuple[str, str]]) -> Path:
    """A 612 x 792 pt page with one 2 x 2 px image, drawn 100 x 50 pt at the origin of the
    innermost of the nested Form XObjects `forms`: each is (the `cm` before its `Do`, its
    `/Matrix`), outermost first. Written byte by byte, so the nesting is exactly as given."""

    def stream(head: str, body: str | bytes) -> bytes:
        data = body.encode() if isinstance(body, str) else body
        return f"<< {head} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"

    n = len(forms)
    page = "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page + "/Resources << /XObject << /X0 5 0 R >> >> /Contents 4 0 R >>",
        stream("", f"q {forms[0][0]} cm /X0 Do Q"),
    ]
    for k, (_, matrix) in enumerate(forms):
        if k + 1 < n:
            inner, draw = f"/X{k + 1}", f"q {forms[k + 1][0]} cm /X{k + 1} Do Q"
        else:
            inner, draw = "/Im", "q 100 0 0 50 0 0 cm /Im Do Q"
        head = (
            f"/Type /XObject /Subtype /Form /BBox [0 0 612 792] /Matrix [{matrix}] "
            f"/Resources << /XObject << {inner} {6 + k} 0 R >> >>"
        )
        objects.append(stream(head, draw))
    image = "/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB "
    objects.append(stream(image + "/BitsPerComponent 8", bytes(12)))
    out, offsets = b"%PDF-1.7\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        data = body.encode() if isinstance(body, str) else body
        out += f"{number} 0 obj\n".encode() + data + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


def nested_pictures_pdf(directory: Path) -> Path:
    """A page with a text layer and two raster pictures without text: a small one, 100 x 50 pt at
    (150, 200), drawn first, and a large one, 300 x 200 pt at (100, 150), drawn over it."""
    Image.new("RGB", (40, 20), (90, 90, 90)).save(directory / "small.png")
    Image.new("RGB", (60, 40), (200, 200, 200)).save(directory / "large.png")
    place = "#place(top + left, dx: {}pt, dy: {}pt)[{}]\n"
    source = PAGE + SERIF + place.format(72, 60, "Ordinary text that the text layer holds.")
    source += place.format(150, 200, '#image("small.png", width: 100pt, height: 50pt)')
    source += place.format(100, 150, '#image("large.png", width: 300pt, height: 200pt)')
    typ = directory / "nested_pictures.typ"
    typ.write_text(source, encoding="utf-8")
    data = typst.compile(str(typ), root=str(directory), ignore_system_fonts=True)
    return _write(directory, "nested_pictures.pdf", data)


def build_all(directory: Path) -> dict:
    return {
        "two_column": two_column_pdf(directory),
        "code": code_pdf(directory),
        "formula": formula_pdf(directory),
        "blank": blank_middle_pdf(directory),
        "hyphen": hyphen_pdf(directory),
        "scanned": scanned_pdf(directory),
        "tall": tall_pdf(directory),
        "photo": photo_pdf(directory),
        "shapes": shapes_pdf(directory),
        "contents": contents_pdf(directory),
        "contents_layouts": contents_layouts_pdf(directory),
        "column_layouts": column_layouts_pdf(directory),
        "picture_text": picture_text_pdf(directory),
        "nested_pictures": nested_pictures_pdf(directory),
    }


FONT_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,;:!?'-"


def make_font(
    chars: str = FONT_CHARS, flavor: str | None = None, small_caps: bool = False
) -> bytes:
    """A real OpenType font (CFF outlines) with one square glyph per character. With `small_caps`
    every lowercase letter also has a `.sc` glyph that an `smcp` feature substitutes for it."""
    names = [".notdef", *(f"u{ord(c):04X}" for c in chars)]
    lower = [f"u{ord(c):04X}" for c in chars if c.islower()] if small_caps else []
    order = names + [f"{name}.sc" for name in lower]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({ord(c): f"u{ord(c):04X}" for c in chars})
    pen = T2CharStringPen(600, None)
    pen.moveTo((0, 0))
    for point in ((0, 500), (500, 500), (500, 0)):
        pen.lineTo(point)
    pen.closePath()
    glyphs = dict.fromkeys(order, pen.getCharString())
    fb.setupCFF("FixtureSerif", {"FullName": "Fixture Serif"}, glyphs, {})
    fb.setupHorizontalMetrics({name: (600, 0) for name in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Fixture Serif", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    if lower:
        subs = "".join(f"sub {name} by {name}.sc;" for name in lower)
        addOpenTypeFeaturesFromString(fb.font, f"feature smcp {{{subs}}} smcp;")
    out = BytesIO()
    fb.save(out)
    if flavor:
        font = TTFont(BytesIO(out.getvalue()))
        font.flavor = flavor
        out = BytesIO()
        font.save(out)
    return out.getvalue()


def image_bytes(size: tuple[int, int], fmt: str, mode: str = "RGB", seed: int = 1, **save) -> bytes:
    """A deterministic blocky picture; a random 1/10 scale image blown up keeps files realistic."""
    rng = random.Random(seed)
    small = (max(size[0] // 10, 1), max(size[1] // 10, 1))
    channels = len(Image.new(mode, (1, 1)).getbands())
    im = Image.frombytes(
        mode, small, bytes(rng.randrange(256) for _ in range(small[0] * small[1] * channels))
    )
    out = BytesIO()
    im.resize(size, Image.Resampling.NEAREST).save(out, fmt, **save)
    return out.getvalue()


def make_epub(path: Path, files: dict[str, bytes | str]) -> Path:
    """Write a raw EPUB zip with `mimetype` first and stored, then the files exactly as given.
    Unlike write_epub_zip it keeps OS junk and odd names, so the optimizer has something to drop."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return path


_XML = '<?xml version="1.0" encoding="utf-8"?>\n'
_NS = 'xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
_CSS = """\
@font-face { font-family: "Fixture Serif"; src: url(../fonts/serif.otf) format("opentype"); }
body { font-family: "Fixture Serif", serif; margin: 0 }
.fl { float: left; width: 40% }
.row { display: flex; justify-content: space-between }
.abs { position: absolute; top: 0 }
.cols { column-count: 2; columns: 2 }
.spacer { background-image: url(../img/spacer.png); height: 1em }
.logo { background: url("../img/logo.png") no-repeat; color: #333 }
"""
SECTIONS, PARAGRAPHS = 25, 25  # the big chapter: 625 paragraphs, about 250 KB


def xhtml_page(title: str, body: str, doctype: str = "<!DOCTYPE html>", head: str = "") -> str:
    return (
        f'{_XML}{doctype}\n<html {_NS} lang="en" xml:lang="en">\n<head><title>{title}</title>'
        f'<link rel="stylesheet" type="text/css" href="../css/style.css"/>{head}</head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _big_chapter() -> str:
    text = "The quick brown fox jumps over the lazy dog while the band plays on and on. " * 5
    parts = ['<h1 id="top">The Big Chapter</h1>']
    for s in range(1, SECTIONS + 1):
        parts.append(f'<h2 id="sec-{s}">Section {s}</h2>')
        for p in range(1, PARAGRAPHS + 1):
            link = ""
            if s == 1 and p == 1:
                link = f' <a href="#sec-{SECTIONS}">last section</a>'
            if s == SECTIONS and p == PARAGRAPHS:
                link = ' <a href="#sec-1">first section</a>'
            parts.append(f'<p id="p-{s}-{p}">{s}.{p} {text}{link}</p>')
    return xhtml_page("Big", "\n".join(parts))


def _opf(items: list[tuple], spine: list[str]) -> str:
    def item(ident: str, href: str, media: str, props: str) -> str:
        extra = f' properties="{props}"' if props else ""
        return f'<item id="{ident}" href="{href}" media-type="{media}"{extra}/>'

    manifest = "\n".join(item(*entry) for entry in items)
    refs = "\n".join(f'<itemref idref="{i}"/>' for i in spine)
    return (
        f'{_XML}<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="uid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '<dc:identifier id="uid">urn:uuid:11111111-2222-3333-4444-555555555555</dc:identifier>\n'
        "<dc:title>Messy Book</dc:title>\n<dc:language>en</dc:language>\n"
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>\n'
        '<meta name="cover" content="cover-image"/>\n</metadata>\n'
        f'<manifest>\n{manifest}\n</manifest>\n<spine toc="ncx">\n{refs}\n</spine>\n</package>\n'
    )


def make_messy_epub(directory: Path) -> Path:
    """A publisher-style EPUB (content in OPS/, files in sub-folders) with everything the optimizer
    must handle: a progressive 1650x835 JPEG, an RGBA PNG, a GIF, a WebP, a 10x10 spacer, an SVG
    cover wrapper, an OTF font with @font-face, CSS with float and display:flex, a data: URI image
    (twice), a 250 KB chapter, a page with named HTML entities, an SVG file, an unused image and
    OS junk."""
    gif = Image.new("P", (120, 80), 0)
    gif.putpalette([255, 255, 255, 0, 0, 0, 200, 0, 0] + [0, 0, 0] * 253)
    draw = ImageDraw.Draw(gif)
    draw.rectangle((10, 10, 60, 50), fill=1)
    draw.rectangle((40, 30, 100, 70), fill=2)
    gif_bytes = BytesIO()
    gif.save(gif_bytes, "GIF")
    uri = (
        "data:image/png;base64," + base64.b64encode(image_bytes((200, 200), "PNG", seed=3)).decode()
    )
    ch1 = "\n".join(
        [
            '<h1 id="c1">Chapter One</h1>',
            '<p class="fl" style="float:left;color:#222">Floated text.</p>',
            '<div class="row"><p>Flex row</p></div>',
            '<p><img src="../img/photo.jpg" alt="photo"/></p>',
            '<p><img src="../img/logo.png" alt="logo" class="logo"/></p>',
            '<p><img src="../img/anim.gif" alt="gif"/><img src="../img/pic.webp" alt="webp"/></p>',
            '<p><img src="../img/spacer.png" alt="" width="10" height="10"/> after the spacer</p>',
            f'<p><img src="{uri}" alt="inline"/> and again <img src="{uri}" alt="again"/></p>',
            '<p><img src="../img/diagram.svg" alt="diagram"/></p>',
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                '<circle cx="20" cy="20" r="10"/></svg>'
            ),
            '<p><a href="big.xhtml#sec-12">Section 12</a> and <a href="#c1">top</a></p>',
        ]
    )
    ch2 = '<h1 id="c2">Chapter&nbsp;Two</h1>\n<p>Caf&eacute; &mdash; &copy; 2026 &amp; more.</p>'
    cover = (
        '<div class="cover"><svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" width="100%" height="100%" '
        'viewBox="0 0 600 800" preserveAspectRatio="none">'
        '<image width="600" height="800" xlink:href="../img/cover.jpg"/></svg></div>'
    )
    sections = [f"xhtml/big.xhtml#sec-{s}" for s in range(1, SECTIONS + 1)]
    nav_links = "".join(
        f'<li><a href="{h}">Section {i}</a></li>' for i, h in enumerate(sections, 1)
    )
    nav = (
        f'{_XML}<!DOCTYPE html>\n<html {_NS} lang="en"><head><title>Contents</title></head>\n<body>'
        '<nav epub:type="toc"><ol><li><a href="xhtml/ch1.xhtml">One</a></li>'
        '<li><a href="xhtml/ch2.xhtml">Two</a></li>'
        f'<li><a href="xhtml/big.xhtml">Big</a><ol>{nav_links}</ol></li></ol></nav>'
        "</body></html>\n"
    )
    points = [("One", "xhtml/ch1.xhtml"), ("Two", "xhtml/ch2.xhtml"), ("Big", "xhtml/big.xhtml")]
    points += [(f"Section {i}", h) for i, h in enumerate(sections, 1)]
    ncx_points = "".join(
        f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{t}</text></navLabel>'
        f'<content src="{h}"/></navPoint>'
        for n, (t, h) in enumerate(points, 1)
    )
    ncx = (
        f'{_XML}<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>'
        '<meta name="dtb:uid" content="urn:uuid:11111111-2222-3333-4444-555555555555"/>'
        '<meta name="dtb:depth" content="1"/><meta name="dtb:totalPageCount" content="0"/>'
        '<meta name="dtb:maxPageNumber" content="0"/></head>'
        f"<docTitle><text>Messy Book</text></docTitle><navMap>{ncx_points}</navMap></ncx>\n"
    )
    xhtml, img, png, jpeg = "application/xhtml+xml", "img/", "image/png", "image/jpeg"
    items = [
        ("nav", "nav.xhtml", xhtml, "nav"),
        ("ncx", "toc.ncx", "application/x-dtbncx+xml", ""),
        ("css", "css/style.css", "text/css", ""),
        ("font", "fonts/serif.otf", "font/otf", ""),
        ("cover", "xhtml/cover.xhtml", xhtml, "svg"),
        ("cover-image", f"{img}cover.jpg", jpeg, "cover-image"),
        ("ch1", "xhtml/ch1.xhtml", xhtml, "svg"),
        ("ch2", "xhtml/ch2.xhtml", xhtml, ""),
        ("big", "xhtml/big.xhtml", xhtml, ""),
        ("photo", f"{img}photo.jpg", jpeg, ""),
        ("logo", f"{img}logo.png", png, ""),
        ("anim", f"{img}anim.gif", "image/gif", ""),
        ("webp", f"{img}pic.webp", "image/webp", ""),
        ("spacer", f"{img}spacer.png", png, ""),
        ("diagram", f"{img}diagram.svg", "image/svg+xml", ""),
        ("unused", f"{img}unused.png", png, ""),
    ]
    spacer = BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(spacer, "PNG")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
        '<rect width="50" height="50"/></svg>'
    )
    files = {
        "META-INF/container.xml": (
            f'{_XML}<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OPS/package.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>\n'
        ),
        "OPS/package.opf": _opf(items, ["cover", "ch1", "ch2", "big"]),
        "OPS/nav.xhtml": nav,
        "OPS/toc.ncx": ncx,
        "OPS/css/style.css": _CSS,
        "OPS/fonts/serif.otf": make_font(),
        "OPS/xhtml/cover.xhtml": xhtml_page("Cover", cover),
        "OPS/xhtml/ch1.xhtml": xhtml_page("One", ch1, head="<style>.x{float:right}</style>"),
        "OPS/xhtml/ch2.xhtml": xhtml_page("Two", ch2),
        "OPS/xhtml/big.xhtml": _big_chapter(),
        "OPS/img/cover.jpg": image_bytes((600, 800), "JPEG", seed=7),
        "OPS/img/photo.jpg": image_bytes((1650, 835), "JPEG", seed=2, progressive=True, quality=90),
        "OPS/img/logo.png": image_bytes((200, 100), "PNG", mode="RGBA", seed=4),
        "OPS/img/anim.gif": gif_bytes.getvalue(),
        "OPS/img/pic.webp": image_bytes((160, 100), "WEBP", seed=6),
        "OPS/img/spacer.png": spacer.getvalue(),
        "OPS/img/diagram.svg": svg,
        "OPS/img/unused.png": image_bytes((60, 60), "PNG", seed=8),
        ".DS_Store": b"junk",
        "OPS/.DS_Store": b"junk",
        "__MACOSX/OPS/._ch1.xhtml": b"junk",
        "Thumbs.db": b"junk",
    }
    return make_epub(directory / "messy.epub", files)
