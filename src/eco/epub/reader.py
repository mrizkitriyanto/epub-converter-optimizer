"""Read an EPUB into a book folder (`book.md` and `images/`), best effort, for the previews."""

import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlsplit

from eco.book import Block, Book
from eco.bookfolder import escape_md, write_book
from eco.epub.optimizer import _count, _local, _Package, _resolve, _unwrap_svg
from eco.events import Finding
from eco.options import Options

_HEADINGS = {f"h{n}": n for n in range(1, 7)}
_INLINE = {
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "del", "dfn", "em", "i", "ins",
    "kbd", "mark", "q", "rp", "rt", "ruby", "s", "samp", "small", "span", "strong", "sub", "sup",
    "time", "u", "var", "wbr",
}  # fmt: skip
_SKIPPED = {"head", "script", "style", "svg", "title", "meta", "link", "hr"}
_MAPPED = {*_HEADINGS, "p", "li", "pre", "table", "img", "body"}
_BOLD, _ITALIC = {"strong", "b"}, {"em", "i"}
_SPACE = re.compile(r"\s+")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_DEVICE_NAME = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE)


def epub_to_book(epub: Path, folder: Path) -> list[Finding]:
    """Write `folder/book.md`, `folder/images/*` and `folder/report.json` for `epub`.

    Raises DRMError for a protected EPUB and ValueError for an unreadable or oversized one.
    """
    package = _Package(epub, Options(device="general"))
    reader = _Reader(package, folder)
    try:
        for path in _spine(package):
            body = package.docs[path].root.find("{*}body") if path in package.docs else None
            if body is not None:
                reader.read_page(path, body)
    except RecursionError as exc:  # XHTML nested hundreds of levels deep
        raise ValueError(f"Not a readable EPUB: {epub.name}") from exc
    meta = package.opf.root.find("{*}metadata")
    book = Book(
        title=_meta(meta, "title") or epub.stem,
        author=", ".join(_metas(meta, "creator")),
        language=_meta(meta, "language") or "en",
        source=epub.name,
        blocks=reader.blocks,
    )
    findings = [*package.findings, *reader.findings()]
    write_book(book, folder, findings)
    return findings


def _spine(package: _Package) -> list[str]:
    path_of = {item.get("id"): path for path, item in package.items.items()}
    return [path_of[ref.get("idref")] for ref in package.spine.findall("{*}itemref")
            if ref.get("idref") in path_of]  # fmt: skip


def _metas(meta: ET.Element | None, name: str) -> list[str]:
    found = meta.findall(f"{{*}}{name}") if meta is not None else []
    return [text for el in found if (text := " ".join("".join(el.itertext()).split()))]


def _meta(meta: ET.Element | None, name: str) -> str:
    return next(iter(_metas(meta, name)), "")


def _text(text: str | None) -> str:
    return escape_md(_SPACE.sub(" ", text or ""))


class _Reader:
    def __init__(self, package: _Package, folder: Path):
        self.package, self.folder = package, folder
        self.blocks: list[Block] = []
        self.flattened = self.unsafe = self.missing = 0
        self.copied: dict[str, str] = {}  # zip path -> path in the folder
        self.owner = ""

    def findings(self) -> list[Finding]:
        found = []
        if self.flattened:
            noun = f"other {_count(self.flattened, 'element')}"
            found.append(Finding(0, "flattened", "info", f"{noun} became paragraphs"))
        if self.unsafe:
            message = f"{_count(self.unsafe, 'image')} outside the EPUB skipped"
            found.append(Finding(0, "unsafe_path", "warning", message))
        if self.missing:
            message = f"{_count(self.missing, 'image')} not found in the EPUB skipped"
            found.append(Finding(0, "missing_image", "warning", message))
        return found

    def read_page(self, path: str, body: ET.Element) -> None:
        self.owner = path
        _unwrap_svg(body)
        self._flow(body, "paragraph")

    # Blocks

    def _flow(self, el: ET.Element, kind: str, level: int = 0) -> None:
        """The content of `el`: inline content becomes blocks of `kind`, block children are read."""
        run: list[str] = [_text(el.text)]
        flat = _local(el) not in _MAPPED and kind == "paragraph"

        def flush() -> None:
            nonlocal flat
            text = "".join(run).strip()
            run.clear()
            if text:
                self.blocks.append(Block(kind, text, level=level, markdown=True))
                self.flattened += flat  # once per element, however many paragraphs it gives
                flat = False

        for child in el:
            tag = _local(child)
            if tag in _SKIPPED:
                pass
            elif tag in _INLINE and not any(_local(d) == "img" for d in child.iter()):
                run.append(self._inline(child))
            else:
                flush()
                self._block(child, kind if kind == "list_item" else "paragraph")
            run.append(_text(child.tail))
        flush()

    def _block(self, el: ET.Element, kind: str) -> None:
        tag = _local(el)
        if tag in _HEADINGS:
            self._flow(el, "heading", _HEADINGS[tag])
        elif tag == "li":
            self._flow(el, "list_item")
        elif tag == "pre":
            self.blocks.append(Block("code", "".join(el.itertext()).strip("\n")))
        elif tag == "img":
            self._image(el)
        elif tag == "table":
            self.blocks.append(Block("table", html=_table_html(el)))
        else:
            self._flow(el, kind)

    # Inline

    def _inline(self, el: ET.Element) -> str:
        """The Markdown of an inline element; elements it does not know keep only their text."""
        tag = _local(el)
        if tag == "br":
            return " "
        inner = _text(el.text)
        for child in el:
            if _local(child) not in _SKIPPED:
                inner += self._inline(child)
            inner += _text(child.tail)
        core = inner.strip()
        if not core:
            return inner
        lead, trail = inner[: len(inner) - len(inner.lstrip())], inner[len(inner.rstrip()) :]
        if tag in _BOLD:
            core = f"**{core}**"
        elif tag in _ITALIC:
            core = f"*{core}*"
        elif tag == "a" and (href := el.get("href", "")):
            core = f"[{core}]({quote(href, safe='/#:?=&%@+,;~')})"
        return lead + core + trail

    # Images

    def _image(self, el: ET.Element) -> None:
        ref = el.get("src", "")
        if urlsplit(ref).scheme:  # a URL or a data: URI: nothing in the EPUB to copy
            return
        target = _resolve(self.owner, ref)
        if target is None:
            return
        if target.startswith(("/", "../")) or target == "..":
            self.unsafe += 1
        elif target not in self.package.files:
            self.missing += 1
        else:
            alt = _SPACE.sub(" ", el.get("alt", "")).strip()
            self.blocks.append(Block("image", alt, image=self._copy(target)))

    def _copy(self, target: str) -> str:
        if target not in self.copied:
            images = self.folder / "images"
            images.mkdir(parents=True, exist_ok=True)
            stem, ext = posixpath.splitext(_safe_name(posixpath.basename(target)))
            name, n = f"{stem}{ext}", 0
            while (images / name).exists():
                n += 1
                name = f"{stem}-{n}{ext}"
            (images / name).write_bytes(self.package.files[target])
            self.copied[target] = f"images/{name}"
        return self.copied[target]


def _table_html(table: ET.Element) -> str:
    copy = ET.fromstring(ET.tostring(table))
    for el in copy.iter():
        el.tag = _local(el)
        el.attrib = {key: value for key, value in el.attrib.items() if "}" not in key}
        el.tail = None if el is copy else el.tail
    return ET.tostring(copy, encoding="unicode", method="html")


def _safe_name(basename: str) -> str:
    """A file name that is safe on every OS: odd characters become `_`, and a Windows device name
    (NUL, CON, COM1 ..., with or without an extension) gets a `_` in front."""
    name = _UNSAFE_NAME.sub("_", basename)
    return f"_{name}" if _DEVICE_NAME.match(name) else name
