import copy
import re
import xml.etree.ElementTree as ET

_WRAPPERS = ("div", "section", "article")
_XMLNS = re.compile(rb"<[^\s>/]+((?:\s+xmlns(?::[\w.-]+)?=\"[^\"]*\")*)")


def _local(el: ET.Element) -> str:
    return el.tag.rpartition("}")[2]


def _blank(text: str | None) -> bool:
    return not (text or "").strip()


def _size(el: ET.Element) -> int:
    """Bytes the element takes inside a document: its own namespace declarations do not count."""
    data = ET.tostring(el, encoding="utf-8")
    return len(data) - len(_XMLNS.match(data)[1])


def anchors(root: ET.Element) -> set[str]:
    """Every id and every <a name> in the tree: the targets of `#fragment` links."""
    found = {el.get("id") for el in root.iter() if el.get("id")}
    return found | {el.get("name") for el in root.iter() if _local(el) == "a" and el.get("name")}


def split_document(root: ET.Element, room: int) -> list[ET.Element]:
    """Split an XHTML tree into parts that take at most `room` bytes where that is possible.

    The cut falls between the children of the body or, when the body holds a single wrapper
    (div, section, article, possibly nested), between the children of that wrapper. Each part
    repeats the wrapper without its id, except the first. A child larger than `room` becomes a
    part of its own. Returns `[root]` when there is nothing to cut.
    """
    body = root.find("{*}body")
    if body is None:
        return [root]
    holder, depth = body, 0
    while (
        len(holder) == 1
        and _local(holder[0]) in _WRAPPERS
        and _blank(holder.text)
        and _blank(holder[0].tail)
    ):
        holder, depth = holder[0], depth + 1
    children = list(holder)
    sizes = [_size(child) for child in children]
    room -= len(ET.tostring(root, encoding="utf-8")) - sum(sizes)  # head, body and wrappers
    groups: list[list[ET.Element]] = [[]]
    used = 0
    for child, size in zip(children, sizes):
        if groups[-1] and used + size > room:
            groups.append([])
            used = 0
        groups[-1].append(child)
        used += size
    if len(groups) == 1:
        return [root]
    text, holder.text = holder.text, None
    holder[:] = []  # what is left is the skeleton every part starts from
    parts = []
    for number, group in enumerate(groups):
        part = copy.deepcopy(root)
        node = part.find("{*}body")
        for _ in range(depth):
            node = node[0]
            if number:
                node.attrib.pop("id", None)
        node.text = None if number else text
        node.extend(group)
        parts.append(part)
    return parts
