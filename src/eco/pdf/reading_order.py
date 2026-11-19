"""Reading-order fix-up: detect multi-column pages and reorder their blocks with an XY-cut."""

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import PageInfo

_MARGIN = 6.0


def is_multicolumn(blocks: list[Block], width: float) -> bool:
    """True when the narrow blocks of a page split into a left and a right column.

    A block that crosses the centre line (a centred title, a full-width figure) spans both
    columns and is ignored.
    """
    middle = width / 2
    narrow = [
        b
        for b in blocks
        if b.bbox
        and b.bbox[2] - b.bbox[0] < 0.6 * width
        and not (b.bbox[0] < middle - _MARGIN and b.bbox[2] > middle + _MARGIN)
    ]
    left = [b for b in narrow if b.bbox[2] <= middle + _MARGIN]
    right = [b for b in narrow if b.bbox[0] >= middle - _MARGIN]
    return len(left) >= 2 and len(right) >= 2 and len(left) + len(right) == len(narrow)


def xy_cut(items: list[Block], gap: float = 6.0) -> list[Block]:
    """Order blocks (all with a bbox): split on horizontal bands first, then on columns."""
    if len(items) <= 1:
        return items
    for lo, hi in ((1, 3), (0, 2)):
        groups: list[list[Block]] = []
        end = None
        for b in sorted(items, key=lambda b: b.bbox[lo]):
            if end is not None and b.bbox[lo] > end + gap:
                groups.append([b])
            elif groups:
                groups[-1].append(b)
            else:
                groups.append([b])
            end = b.bbox[hi] if end is None else max(end, b.bbox[hi])
        if len(groups) > 1:
            return [x for g in groups for x in xy_cut(g, gap)]
    return sorted(items, key=lambda b: (b.bbox[1], b.bbox[0]))


def fix_reading_order(
    blocks: list[Block], pages: dict[int, PageInfo]
) -> tuple[list[Block], list[Finding]]:
    """Reorder the blocks of each multi-column page. Blocks without a bbox keep their position."""
    positions: dict[int, list[int]] = {}
    for index, b in enumerate(blocks):
        if b.bbox:
            positions.setdefault(b.page, []).append(index)
    result = list(blocks)
    findings = []
    for page, slots in positions.items():
        if page not in pages:
            continue
        page_blocks = [blocks[i] for i in slots]
        if not is_multicolumn(page_blocks, pages[page].width):
            continue
        ordered = xy_cut(page_blocks)
        if ordered == page_blocks:
            continue
        for slot, b in zip(slots, ordered):
            result[slot] = b
        findings.append(
            Finding(
                page, "reading_order_fixed", "info", "Reordered the blocks of a two-column page"
            )
        )
    return result, findings
