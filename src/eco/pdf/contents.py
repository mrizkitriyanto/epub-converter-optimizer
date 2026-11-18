"""Contents and index pages, rebuilt from the PDF text layer in reading order (agent decision Q-23).

Docling reads a page of contents as a table (`document_index`), and its table model forces a
two-column page into a grid whose rows pair entries of both columns. On a page with a text layer
the entries are read again from that layer: full-width lines (part and chapter titles) in their
place, and between them the left column, then the right, top to bottom, one entry per line."""

import re
from dataclasses import replace
from pathlib import Path

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import Bbox, PageInfo, _open, to_pdfium_rect

_GAP = 6.0  # pt: how far a run may reach past the middle of the box and still be in a column
_SAME_LINE = 3.0  # pt: runs whose tops are this close are one line
_PAD = 2.0
_PAGE_NUMBER = re.compile(r"(?<=[\s.\u2026\u00b7])(\d+|[ivxlcdm]+)$")
_ROMAN = re.compile(r"m{0,3}(c[md]|d?c{0,3})(x[cl]|l?x{0,3})(i[xv]|v?i{0,3})")
_LEADER = re.compile(r"(?:\s*[.\u00b7\u2026]){2,}\s*$")


def _runs(pdf: Path, info: PageInfo, bbox: Bbox) -> list[tuple[float, float, str, str]]:
    """The text runs inside `bbox`: (top, left, side, text), side "left", "right" or "wide"."""
    left, bottom, right, top = to_pdfium_rect(info, bbox)
    middle = (left + right) / 2
    runs = []
    with _open(pdf) as document:
        textpage = document[info.number - 1].get_textpage()
        for index in range(textpage.count_rects()):
            x0, y0, x1, y1 = textpage.get_rect(index)
            inside = left - _PAD <= (x0 + x1) / 2 <= right + _PAD
            if not inside or not bottom - _PAD <= (y0 + y1) / 2 <= top + _PAD:
                continue
            # PDFium marks a hyphen at a line end with U+FFFE: keep it as a hyphen
            text = textpage.get_text_bounded(x0, y0, x1, y1).replace("\ufffe", "-").strip()
            if text:
                wide = x0 < middle - _GAP and x1 > middle + _GAP
                side = "wide" if wide else "left" if (x0 + x1) / 2 < middle else "right"
                runs.append((y1, x0, side, " ".join(text.split())))
    return runs


def _lines(runs: list[tuple[float, float, str, str]]) -> list[str]:
    """Runs whose tops are close, as lines from top to bottom, each read left to right."""
    lines: list[list[tuple[float, float, str, str]]] = []
    for run in sorted(runs, key=lambda r: -r[0]):
        if lines and lines[-1][0][0] - run[0] <= _SAME_LINE:
            lines[-1].append(run)
        else:
            lines.append([run])
    return [" ".join(r[3] for r in sorted(line, key=lambda r: r[1])) for line in lines]


def _reading_order(runs: list[tuple[float, float, str, str]]) -> list[str]:
    """A full-width line ends the columns above it, which are read left column first."""
    lines: list[str] = []
    columns: dict[str, list] = {"left": [], "right": []}
    for run in sorted(runs, key=lambda r: -r[0]):
        if run[2] == "wide":
            lines += _lines(columns["left"]) + _lines(columns["right"]) + _lines([run])
            columns = {"left": [], "right": []}
        else:
            columns[run[2]].append(run)
    return lines + _lines(columns["left"]) + _lines(columns["right"])


def _without_page_number(line: str) -> str:
    """A contents line without its print page number and dot leader. A line that is only a
    number (a chapter number on a line of its own) stays as it is."""
    found = _PAGE_NUMBER.search(line)
    if not found or not (found[1].isdigit() or _ROMAN.fullmatch(found[1])):
        return line
    head = _LEADER.sub("", line[: found.start()]).rstrip()
    return head if re.search(r"\w", head) else line


def rebuild_contents(
    pdf: Path, blocks: list[Block], pages: dict[int, PageInfo]
) -> tuple[list[Block], list[Finding]]:
    """Turn each `contents` block into its entries, read from the text layer: a paragraph for each
    line of contents, without the print page numbers; a list item for each line of an index (a
    block in the back half of the book), which keeps its numbers. On a scanned page, or when the
    text layer has nothing in the box, the block is Docling's table."""
    last = max(pages, default=0)
    out: list[Block] = []
    findings: list[Finding] = []
    for block in blocks:
        if block.kind != "contents":
            out.append(block)
            continue
        info = pages.get(block.page)
        readable = info is not None and not info.is_scanned and block.bbox is not None
        lines = _reading_order(_runs(pdf, info, block.bbox)) if readable else []
        if not lines:
            out.append(replace(block, kind="table"))
            continue
        if block.page > last / 2:
            out += [Block("list_item", line, page=block.page) for line in lines]
            message = "Index read again from the PDF text layer, in reading order."
        else:
            entries = [entry for line in lines if (entry := _without_page_number(line))]
            out += [Block("paragraph", entry, page=block.page) for entry in entries]
            message = "Contents read again from the PDF text layer, without print page numbers."
        findings.append(Finding(block.page, "contents_rebuilt", "info", message))
    return out, findings
