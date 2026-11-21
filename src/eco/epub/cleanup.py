"""Blocks and pages with nothing to read. On an e-ink reader each one can cost a blank screen."""

import xml.etree.ElementTree as ET

_BLOCKS = {"p", "div"}
_MEDIA = {"img", "svg", "image", "video", "audio", "object"}


def _local(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2] if isinstance(el.tag, str) else ""


def _blank(text: str | None) -> bool:
    return not (text or "").replace("\xa0", " ").strip()


def _remove(parent: ET.Element, child: ET.Element) -> None:
    """Remove `child`, keeping the text that follows it."""
    index = list(parent).index(child)
    if child.tail:
        if index:
            previous = parent[index - 1]
            previous.tail = (previous.tail or "") + child.tail
        else:
            parent.text = (parent.text or "") + child.tail
    parent.remove(child)


def _empty_block(el: ET.Element) -> bool:
    """A p or div with no text, no id, and nothing in it but line breaks."""
    if _local(el) not in _BLOCKS or el.get("id") is not None or not _blank(el.text):
        return False
    return all(_local(child) == "br" and _blank(child.tail) for child in el)


def drop_empty_blocks(body: ET.Element) -> int:
    """Remove empty paragraphs and divs, and collapse runs of <br/> to one. Returns how many
    elements went."""
    removed = 0

    def visit(parent: ET.Element) -> None:
        nonlocal removed
        for child in list(parent):
            visit(child)  # first, so a div that held only empty paragraphs is empty itself
            if _empty_block(child):
                _remove(parent, child)
                removed += 1
        previous = None
        for child in list(parent):
            if (
                previous is not None
                and _local(previous) == "br"
                and _local(child) == "br"
                and _blank(previous.tail)
                and child.get("id") is None
            ):
                _remove(parent, child)
                removed += 1
                continue
            previous = child

    visit(body)
    return removed


def is_empty_document(body: ET.Element) -> bool:
    """True when a page has no text to read and no picture or media to show."""
    if not _blank("".join(body.itertext())):
        return False
    return not any(_local(el) in _MEDIA for el in body.iter())
