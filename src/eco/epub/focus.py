"""Embed Focus Mode in EPUB XHTML without changing its text or links."""

import xml.etree.ElementTree as ET
from unicodedata import combining, name

_XHTML = "http://www.w3.org/1999/xhtml"
_SKIP = {"b", "code", "kbd", "math", "pre", "samp", "script", "style", "svg"}


def _letter(char: str) -> bool:
    return name(char, "").startswith(("LATIN ", "GREEK ", "CYRILLIC ")) and char.isalpha()


def focus_letters(count: int) -> int:
    """How many of a word's letters are bold: 1 up to 3 letters, 2 of 4, else the nearest 40%."""
    if count <= 3:
        return 1
    if count == 4:
        return 2
    return (4 * count + 5) // 10


def focus_body(body: ET.Element, weight: int) -> None:
    """Wrap the initial letters of words in presentational bold elements of that weight."""

    def clear(parent: ET.Element) -> None:
        for child in list(parent):
            clear(child)
            if (
                child.tag == f"{{{_XHTML}}}b"
                and child.get("class") == "eco-focus"
                and not len(child)
            ):
                index = list(parent).index(child)
                previous = parent[index - 1] if index else None
                text = (child.text or "") + (child.tail or "")
                if previous is None:
                    parent.text = (parent.text or "") + text
                else:
                    previous.tail = (previous.tail or "") + text
                parent.remove(child)

    def visit(parent: ET.Element) -> None:
        children = list(parent)
        if parent.text:
            insert(parent, None, parent.text)
        for child in children:
            if child.tag.startswith(f"{{{_XHTML}}}") and child.tag.rpartition("}")[2] not in _SKIP:
                visit(child)
            if child.tail:
                insert(parent, child, child.tail)

    def insert(parent: ET.Element, previous: ET.Element | None, source: str) -> None:
        if previous is None:
            parent.text = None
            index = 0
        else:
            previous.tail = None
            index = list(parent).index(previous) + 1
        anchor = previous
        i = 0
        while i < len(source):
            if not _letter(source[i]):
                if anchor is None:
                    parent.text = (parent.text or "") + source[i]
                else:
                    anchor.tail = (anchor.tail or "") + source[i]
                i += 1
                continue
            clusters: list[str] = []
            while i < len(source) and _letter(source[i]):
                start = i
                i += 1
                while i < len(source) and combining(source[i]):
                    i += 1
                clusters.append(source[start:i])
            n = focus_letters(len(clusters))
            bold = ET.Element(
                f"{{{_XHTML}}}b", {"class": "eco-focus", "style": f"font-weight:{weight}"}
            )
            bold.text = "".join(clusters[:n])
            bold.tail = "".join(clusters[n:])
            parent.insert(index, bold)
            index += 1
            anchor = bold

    clear(body)
    visit(body)
