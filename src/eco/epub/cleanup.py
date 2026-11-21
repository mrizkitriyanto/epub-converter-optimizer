"""Blocks and pages with nothing to read. On an e-ink reader each one can cost a blank screen."""

import xml.etree.ElementTree as ET
from collections.abc import Callable

_BLOCKS = {"p", "div"}
_MEDIA = {"img", "svg", "image", "video", "audio", "object"}

Gone = Callable[[ET.Element], bool]  # a picture whose file the optimizer removed


def _never(el: ET.Element) -> bool:
    return False


def _local(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2] if isinstance(el.tag, str) else ""


def _blank(text: str | None) -> bool:
    return not (text or "").replace("\xa0", " ").strip()


def _empty_block(el: ET.Element, gone: Gone) -> bool:
    """A p or div with no text and no id, holding nothing but line breaks and pictures that are
    gone."""
    if _local(el) not in _BLOCKS or el.get("id") is not None or not _blank(el.text):
        return False
    return all(
        (_local(child) == "br" or gone(child)) and child.get("id") is None and _blank(child.tail)
        for child in el
    )


def drop_empty_blocks(body: ET.Element, gone: Gone = _never) -> int:
    """Remove empty paragraphs and divs, and collapse runs of <br/> to one. Returns how many
    elements went. Each parent's children are rebuilt in one pass."""
    removed = 0

    def visit(parent: ET.Element) -> None:
        nonlocal removed
        kept: list[ET.Element] = []
        text = parent.text
        for child in list(parent):
            visit(child)  # first, so a div that held only empty paragraphs is empty itself
            previous = kept[-1] if kept else None
            extra_break = (
                previous is not None
                and _local(previous) == "br"
                and _local(child) == "br"
                and _blank(previous.tail)
                and child.get("id") is None
            )
            if _empty_block(child, gone) or extra_break:
                removed += 1
                if child.tail:  # the text after it stays
                    if previous is not None:
                        previous.tail = (previous.tail or "") + child.tail
                    else:
                        text = (text or "") + child.tail
                continue
            kept.append(child)
        if len(kept) != len(parent):
            parent[:] = kept
            parent.text = text

    visit(body)
    return removed


def is_empty_document(body: ET.Element, gone: Gone = _never) -> bool:
    """True when a page has no text to read and no picture or media left to show."""
    if not _blank("".join(body.itertext())):
        return False
    return not any(_local(el) in _MEDIA and not gone(el) for el in body.iter())
