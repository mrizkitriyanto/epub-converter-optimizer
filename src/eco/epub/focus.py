"""Embed Focus Mode in EPUB XHTML without changing its text or links."""

import xml.etree.ElementTree as ET
from unicodedata import combining, name

_XHTML = "http://www.w3.org/1999/xhtml"
_SKIP = {"b", "code", "kbd", "math", "pre", "samp", "script", "style", "svg"}
_PERCENT = {"low": 30, "medium": 50, "high": 70}


def _letter(char: str) -> bool:
    return name(char, "").startswith(("LATIN ", "GREEK ", "CYRILLIC ")) and char.isalpha()


def focus_body(body: ET.Element, strength: str) -> None:
    """Wrap the initial letters of words in presentational bold elements."""
    percent = _PERCENT[strength]

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
            n = min(len(clusters) - 1, max(1, (len(clusters) * percent + 99) // 100))
            if len(clusters) == 1:
                n = 1
            bold = ET.Element(f"{{{_XHTML}}}b", {"class": "eco-focus", "style": "font-weight:700"})
            bold.text = "".join(clusters[:n])
            bold.tail = "".join(clusters[n:])
            parent.insert(index, bold)
            index += 1
            anchor = bold

    clear(body)
    visit(body)
