"""Heading levels: from the PDF bookmarks when there are any, from a heuristic when not."""

import re
from dataclasses import replace
from difflib import SequenceMatcher

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import Bookmark

_MIN_RATIO = 0.8
_MAX_LEVEL = 6
_CHAPTER = re.compile(r"^(Chapter|Bab|BAB)\s+\w+")
_CHAPTER_LABEL = re.compile(r"^(?:chapter|bab)\s+(\d+)\s*[:.]?\s*")


def assign_heading_levels(
    blocks: list[Block], marks: list[Bookmark]
) -> tuple[list[Block], list[Finding]]:
    if not marks:
        return [_heuristic(block) for block in blocks], []

    levels: dict[int, int] = {}  # block index -> level taken from its bookmark
    unmatched: list[Bookmark] = []
    for mark in marks:
        index = _best_heading(blocks, levels, mark)
        if index is None:
            unmatched.append(mark)
        else:
            levels[index] = min(_MAX_LEVEL, mark.level + 1)
    stray_level = min(_MAX_LEVEL, max(mark.level for mark in marks) + 2)

    first = min((block.page for block in blocks), default=0)
    last = max((block.page for block in blocks), default=0)
    added: dict[int, list[Block]] = {}  # block index -> headings to insert before it
    findings = []
    for mark in unmatched:
        if not first <= mark.page <= last:
            continue
        before = next(i for i, block in enumerate(blocks) if block.page >= mark.page)
        title = mark.title.strip()
        level = min(_MAX_LEVEL, mark.level + 1)
        added.setdefault(before, []).append(Block("heading", title, level=level, page=mark.page))
        message = f"Heading added from the PDF bookmark: {title}"
        findings.append(Finding(mark.page, "heading_added", "info", message))

    out = []
    for index, block in enumerate(blocks):
        out.extend(added.get(index, []))
        if block.kind == "heading":
            block = replace(block, level=levels.get(index, stray_level))
        out.append(block)
    return out, findings


def _key(title: str) -> str:
    """A title as it is compared. A book's bookmark often says "Chapter 3: Title" where the page
    says "3 Title" (or the other way round), so a leading chapter label becomes its number."""
    return _CHAPTER_LABEL.sub(r"\1 ", title.lower().strip()).strip()


def _best_heading(blocks: list[Block], taken: dict[int, int], mark: Bookmark) -> int | None:
    candidates = [
        (SequenceMatcher(None, _key(block.text), _key(mark.title)).ratio(), -index)
        for index, block in enumerate(blocks)
        if block.kind == "heading" and index not in taken and abs(block.page - mark.page) <= 1
    ]
    ratio, negative_index = max(candidates, default=(0.0, 0))
    return -negative_index if ratio >= _MIN_RATIO else None


def _heuristic(block: Block) -> Block:
    if block.kind != "heading":
        return block
    letters = [char for char in block.text if char.isalpha()]
    all_caps = len(letters) >= 4 and all(char.isupper() for char in letters)
    return replace(block, level=1 if all_caps or _CHAPTER.match(block.text) else 2)
