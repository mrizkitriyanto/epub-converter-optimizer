"""Code block fix-up: rebuild each block's lines from the PDF text layer, or crop it to an image."""

from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from statistics import median

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import HYPHEN_MARKS, Bbox, PageInfo, _open, crop, to_pdfium_rect

_PAD = 2.0
_LINE_TOLERANCE = 2.0


def reextract_code(pdf: Path, info: PageInfo, bbox: Bbox) -> str | None:
    """Return the code in `bbox` with its lines and indentation, or None when no chars are there.

    PDFium collapses runs of spaces, so spaces are rebuilt from the x positions of the visible
    chars. Loose char boxes are used: their top, left and width come from the font metrics, so
    they do not change with the glyph shape.
    """
    left, bottom, right, top = to_pdfium_rect(info, bbox)
    with _open(pdf) as document:
        textpage = document[info.number - 1].get_textpage()
        chars = []  # (x0, x1, top, char)
        for index in range(textpage.count_chars()):
            char = textpage.get_text_range(index, 1).translate(HYPHEN_MARKS)
            if not char.strip():
                continue
            x0, y0, x1, y1 = textpage.get_charbox(index, loose=True)
            if (
                left - _PAD <= (x0 + x1) / 2 <= right + _PAD
                and bottom - _PAD <= (y0 + y1) / 2 <= top + _PAD
            ):
                chars.append((x0, x1, y1, char))
    if not chars:
        return None

    width = median(x1 - x0 for x0, x1, _, _ in chars)
    min_x0 = min(x0 for x0, _, _, _ in chars)
    lines: list[list[tuple[float, float, float, str]]] = []
    for item in sorted(chars, key=lambda c: -c[2]):
        if lines and lines[-1][0][2] - item[2] <= _LINE_TOLERANCE:
            lines[-1].append(item)
        else:
            lines.append([item])

    rebuilt = []
    for line in lines:
        line.sort()
        text = " " * round((line[0][0] - min_x0) / width) + line[0][3]
        for (_, previous_x1, _, _), (x0, _, _, char) in pairwise(line):
            text += (" " if x0 - previous_x1 > 0.5 * width else "") + char
        rebuilt.append(text.rstrip())
    return "\n".join(rebuilt)


def fix_code_blocks(
    pdf: Path, blocks: list[Block], pages: dict[int, PageInfo], images_dir: Path
) -> tuple[list[Block], list[Finding]]:
    """Restore the lines of code blocks; on scanned pages turn each code block into an image."""
    fixed: list[Block] = []
    findings: list[Finding] = []
    images_on_page: dict[int, int] = {}
    for block in blocks:
        info = pages.get(block.page)
        if block.kind != "code" or block.bbox is None or info is None:
            fixed.append(block)
        elif info.is_scanned:
            n = images_on_page[block.page] = images_on_page.get(block.page, 0) + 1
            name = f"p{block.page:04d}-code-{n}.png"
            images_dir.mkdir(parents=True, exist_ok=True)
            crop(pdf, block.page, block.bbox).save(images_dir / name)
            fixed.append(replace(block, kind="image", image=f"images/{name}"))
            findings.append(
                Finding(
                    block.page,
                    "code_as_image",
                    "info",
                    "Scanned page: code block kept as an image.",
                )
            )
        else:
            text = reextract_code(pdf, info, block.bbox)
            if text is None:
                fixed.append(block)
                findings.append(
                    Finding(
                        block.page,
                        "code_not_restored",
                        "warning",
                        "Could not read this code block from the PDF text layer; "
                        "kept the extracted text.",
                    )
                )
            elif text == block.text:
                fixed.append(block)
            else:
                fixed.append(replace(block, text=text))
                findings.append(
                    Finding(
                        block.page,
                        "code_restored",
                        "info",
                        "Code block rebuilt from the PDF text layer.",
                    )
                )
    return fixed, findings
