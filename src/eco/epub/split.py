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


def pack(sizes: list[int], room: int, heads: set[int] = frozenset()) -> list[list[int]]:
    """Group consecutive items into runs of at most `room` bytes; an item larger than `room` is a
    run of its own. When a run is full, the cut moves back to its last heading (an index in
    `heads`) if at least half the room stays behind, so a part starts at a heading rather than in
    the middle of a section."""
    groups: list[list[int]] = [[]]
    used = 0
    for item, size in enumerate(sizes):
        if groups[-1] and used + size > room:
            run, moved, kept = groups[-1], [], used
            # a heading that does not fit starts the next part anyway
            for k in range(len(run) - 1, 0, -1) if item not in heads else ():
                kept -= sizes[run[k]]
                if kept < room // 2:
                    break
                if run[k] in heads:
                    if used - kept + size <= room:
                        moved = run[k:]
                        del run[k:]
                    break
            groups.append(moved)
            used = sum(sizes[i] for i in moved)
        groups[-1].append(item)
        used += size
    return groups


def _heading(el: ET.Element) -> bool:
    """A heading, or a wrapper that starts with one."""
    if re.fullmatch(r"h[1-6]", _local(el)):
        return True
    return _local(el) in _WRAPPERS and len(el) > 0 and _blank(el.text) and _heading(el[0])


def _open(el: ET.Element, room: int) -> list[ET.Element]:
    """A wrapper larger than `room` as copies of itself that each hold a run of its children,
    the id on the first only. Anything else, or a wrapper with text between its children (which
    a cut would move), is returned as it is."""
    if (
        _local(el) not in _WRAPPERS
        or _size(el) <= room
        or not _blank(el.text)
        or any(not _blank(child.tail) for child in el)
    ):
        return [el]
    room -= _size(el) - sum(_size(child) for child in el)  # its own tags
    kids = [piece for child in el for piece in _open(child, room)]
    groups = pack(
        [_size(kid) for kid in kids], room, {i for i, k in enumerate(kids) if _heading(k)}
    )
    if len(groups) == 1:
        return [el]
    shells = []
    for number, group in enumerate(groups):
        attrib = {k: v for k, v in el.attrib.items() if not (number and k == "id")}
        shell = ET.Element(el.tag, attrib)
        shell.text, shell.tail = el.text, el.tail
        shell.extend(kids[i] for i in group)
        shells.append(shell)
    return shells


def split_document(root: ET.Element, room: int) -> list[ET.Element]:
    """Split an XHTML tree into parts that take at most `room` bytes where that is possible.

    The cut falls between the children of the body or, when the body holds a single wrapper
    (div, section, article, possibly nested), between the children of that wrapper. Each part
    repeats the wrapper without its id, except the first. A child that is a wrapper larger than
    `room` is opened the same way (an InDesign export holds a whole chapter in one container
    beside an empty one). The cut moves back to a heading where it can. Any other child larger
    than `room` becomes a part of its own. Returns `[root]` when there is nothing to cut.
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
    room -= len(ET.tostring(root, encoding="utf-8")) - sum(_size(child) for child in holder)
    children = [piece for child in holder for piece in _open(child, room)]
    heads = {i for i, child in enumerate(children) if _heading(child)}
    groups = [[children[i] for i in run] for run in pack([_size(c) for c in children], room, heads)]
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
