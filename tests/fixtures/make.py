"""Synthetic PDFs compiled with Typst. Every bbox is in PDF points, top-left origin, relative to
the page's CropBox (the same convention as the pipeline's blocks)."""

from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import typst
from PIL import Image, ImageChops

Bbox = tuple[float, float, float, float]

PAGE = "#set page(width: 612pt, height: 792pt, margin: 0pt)\n"
SERIF = '#set text(font: "Libertinus Serif", size: 11pt)\n'
MONO = '#show raw: set text(font: "DejaVu Sans Mono", size: 10pt)\n'
CODE_LINES = [
    "100014A0 WlxLoggedOutSAS",
    "    push esi",
    "    push edi",
    "    call Call_msgina_dll_function",
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


def build_all(directory: Path) -> dict:
    return {
        "two_column": two_column_pdf(directory),
        "code": code_pdf(directory),
        "formula": formula_pdf(directory),
        "blank": blank_middle_pdf(directory),
        "hyphen": hyphen_pdf(directory),
        "scanned": scanned_pdf(directory),
    }
