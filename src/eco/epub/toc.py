"""The table of contents of an EPUB, built from its headings when the book has none that works."""

import posixpath
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

XHTML = "http://www.w3.org/1999/xhtml"
NCX = "http://www.daisy.org/z3986/2005/ncx/"
OPS = "http://www.idpf.org/2007/ops"
_LEVELS = {"h1": 1, "h2": 2, "h3": 3}


@dataclass
class TocEntry:
    level: int
    label: str
    path: str  # zip path of the page
    anchor: str  # id in the page, "" for the page itself


def _local(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2] if isinstance(el.tag, str) else ""


def _text(el: ET.Element) -> str:
    return " ".join("".join(el.itertext()).split())


def headings(pages: list[tuple[str, ET.Element]]) -> list[TocEntry]:
    """The h1 to h3 headings of the pages in order; a heading with no id gets `eco-toc-N`. With no
    heading at all, one entry per page, named by its title or "Section N"."""
    entries = []
    taken = {el.get("id") for _, root in pages for el in root.iter() if el.get("id")}
    added = 0
    for path, root in pages:
        body = root.find(f"{{{XHTML}}}body")
        for el in body.iter() if body is not None else ():
            level = _LEVELS.get(_local(el))
            label = _text(el) if level else ""
            if not label:
                continue
            if not el.get("id"):
                added += 1
                while f"eco-toc-{added}" in taken:
                    added += 1
                el.set("id", f"eco-toc-{added}")
            entries.append(TocEntry(level, label, path, el.get("id")))
    if entries:
        return entries
    for n, (path, root) in enumerate(pages, 1):
        title = root.find(f"{{{XHTML}}}head/{{{XHTML}}}title")
        label = _text(title) if title is not None else ""
        entries.append(TocEntry(1, label or f"Section {n}", path, ""))
    return entries


def broken_share(targets: list[str], exists: Callable[[str], bool]) -> float:
    """The share of the targets that point nowhere; 0 when there are none."""
    if not targets:
        return 0.0
    return sum(not exists(target) for target in targets) / len(targets)


def _href(entry: TocEntry, owner: str) -> str:
    href = quote(posixpath.relpath(entry.path, posixpath.dirname(owner) or "."))
    return f"{href}#{entry.anchor}" if entry.anchor else href


def _nest(
    entries: list[TocEntry], make: Callable[[ET.Element, TocEntry], ET.Element], root: ET.Element
) -> None:
    """Hang each entry under the last entry of a lower level, or under `root`."""
    stack: list[tuple[int, ET.Element]] = []
    for entry in entries:
        while stack and stack[-1][0] >= entry.level:
            stack.pop()
        parent = stack[-1][1] if stack else root
        stack.append((entry.level, make(parent, entry)))


def ncx_map(entries: list[TocEntry], owner: str) -> ET.Element:
    """An NCX navMap of the entries, nested by level; links are relative to `owner`."""
    nav_map = ET.Element(f"{{{NCX}}}navMap")
    order = 0

    def point(parent: ET.Element, entry: TocEntry) -> ET.Element:
        nonlocal order
        order += 1
        el = ET.SubElement(
            parent, f"{{{NCX}}}navPoint", {"id": f"eco-np-{order}", "playOrder": str(order)}
        )
        label = ET.SubElement(el, f"{{{NCX}}}navLabel")
        ET.SubElement(label, f"{{{NCX}}}text").text = entry.label
        ET.SubElement(el, f"{{{NCX}}}content", {"src": _href(entry, owner)})
        return el

    _nest(entries, point, nav_map)
    return nav_map


def nav_body(entries: list[TocEntry], owner: str) -> ET.Element:
    """An EPUB 3 `<nav epub:type="toc">` of the entries, nested by level."""
    nav = ET.Element(f"{{{XHTML}}}nav", {f"{{{OPS}}}type": "toc", "id": "toc"})
    top = ET.SubElement(nav, f"{{{XHTML}}}ol")

    def item(parent: ET.Element, entry: TocEntry) -> ET.Element:
        ol = parent if _local(parent) == "ol" else parent.find(f"{{{XHTML}}}ol")
        if ol is None:
            ol = ET.SubElement(parent, f"{{{XHTML}}}ol")
        li = ET.SubElement(ol, f"{{{XHTML}}}li")
        ET.SubElement(li, f"{{{XHTML}}}a", {"href": _href(entry, owner)}).text = entry.label
        return li

    _nest(entries, item, top)
    return nav


def _entry(level: int, label: str, owner: str, href: str) -> TocEntry:
    parts = urlsplit(href)
    path = posixpath.normpath(posixpath.join(posixpath.dirname(owner), unquote(parts.path)))
    return TocEntry(level, label, path, unquote(parts.fragment))


def entries_from_nav(nav: ET.Element, owner: str) -> list[TocEntry]:
    """The entries of an EPUB 3 toc nav, levels from its nested lists."""
    entries: list[TocEntry] = []

    def walk(ol: ET.Element, level: int) -> None:
        for li in ol.findall(f"{{{XHTML}}}li"):
            link = li.find(f"{{{XHTML}}}a")
            linked = link is not None and bool(link.get("href"))
            if linked:
                image = link.find(f".//{{{XHTML}}}img")
                label = _text(link) or (image.get("alt", "").strip() if image is not None else "")
                label = label or f"Section {len(entries) + 1}"
                entries.append(_entry(level, label, owner, link.get("href")))
            sub = li.find(f"{{{XHTML}}}ol")
            if sub is not None:  # under an unlinked part, its entries keep the part's level
                walk(sub, level + 1 if linked else level)

    top = nav.find(f"{{{XHTML}}}ol")
    if top is not None:
        walk(top, 1)
    return entries


def entries_from_ncx(nav_map: ET.Element, owner: str) -> list[TocEntry]:
    """The entries of an NCX navMap, levels from its nested navPoints."""
    entries: list[TocEntry] = []

    def walk(parent: ET.Element, level: int) -> None:
        for point in parent.findall(f"{{{NCX}}}navPoint"):
            text = point.find(f"{{{NCX}}}navLabel/{{{NCX}}}text")
            content = point.find(f"{{{NCX}}}content")
            if content is not None and content.get("src"):
                label = (_text(text) if text is not None else "") or f"Section {len(entries) + 1}"
                entries.append(_entry(level, label, owner, content.get("src")))
            walk(point, level + 1)

    walk(nav_map, 1)
    return entries
