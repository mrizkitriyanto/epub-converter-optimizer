"""What the acceptance tests measure (spec section 9) and the readers of the files they measure."""

import difflib
import html
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

from PIL import Image

MIN_BLOCK = 3  # a run of fewer matching words is chance, not a copy
_BANNED = {".otf", ".ttf", ".woff", ".woff2", ".svg", ".webp", ".gif"}

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"(?<!\\)\[([^\]]*)\]\([^)]*\)")  # not the `\[1\](x)` that eco writes
_TAG = re.compile(r"<[^>]*>")
_WORD = re.compile(r"[A-Za-z0-9À-ɏ']+")
_PAGE = re.compile(r"<!-- page: (\d+) -->")
_FENCE = re.compile(r"^(`{3,}|~{3,})\n(.*?)\n\1$", re.DOTALL | re.MULTILINE)
_HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL)
_EPUB_NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "o": "http://www.idpf.org/2007/opf",
}


def words(text: str) -> list[str]:
    """Lowercase tokens of Markdown or XHTML: images, link targets and tags are not text."""
    text = _MD_IMAGE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    return _WORD.findall(html.unescape(text).lower())


def _matched(truth: list[str], out: list[str]) -> list[difflib.Match]:
    matcher = difflib.SequenceMatcher(None, truth, out, autojunk=False)
    return [m for m in matcher.get_matching_blocks() if m.size >= MIN_BLOCK]


def sequence_scores(truth: list[str], out: list[str]) -> tuple[float, float]:
    """(precision, recall) of `out` against `truth`, counting only runs of at least 3 words that
    both have in the same order. Precision is the share of `out` in such runs. Recall is the share
    of `truth` in such runs, between the first word that matched and the last."""
    blocks = _matched(truth, out)
    if not blocks:
        return 0.0, 0.0
    matched = sum(m.size for m in blocks)
    span = blocks[-1].a + blocks[-1].size - blocks[0].a
    return matched / len(out), matched / span


def word_recall(truth_page: list[str], out: list[str]) -> float:
    """The share of the words of a transcribed page that `out` has, in order."""
    return sum(m.size for m in _matched(truth_page, out)) / len(truth_page)


def pages(markdown: str, first: int, last: int) -> str:
    """The text of PDF pages `first` to `last` of a book.md, cut at its page markers."""
    parts = _PAGE.split(markdown)  # the front, then a page number and its text, again and again
    return "\n\n".join(
        text.strip()
        for number, text in zip(parts[1::2], parts[2::2])
        if first <= int(number) <= last
    )


def headings(markdown: str) -> list[str]:
    """The headings of a book.md outside code, with the Markdown escapes taken out."""
    return [
        " ".join(re.sub(r"\\(.)", r"\1", heading).split())
        for heading in _HEADING.findall(_FENCE.sub("", markdown))
    ]


def code_blocks(markdown: str) -> list[list[str]]:
    """The lines of each fenced code block, with each run of white space made into one space."""
    return [
        [" ".join(line.split()) for line in body.split("\n")]
        for _, body in _FENCE.findall(markdown)
    ]


def epub_text(path: Path) -> str:
    """The markup inside `<body>` of every spine document of an EPUB, in reading order."""
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", _EPUB_NS).get("full-path")
        opf = ET.fromstring(z.read(opf_path))
        hrefs = {i.get("id"): unquote(i.get("href")) for i in opf.iterfind(".//o:item", _EPUB_NS)}
        folder = posixpath.dirname(opf_path)
        docs = []
        for ref in opf.iterfind(".//o:itemref", _EPUB_NS):
            name = posixpath.normpath(posixpath.join(folder, hrefs[ref.get("idref")]))
            docs.append(z.read(name).decode("utf-8"))
    return "\n".join(m.group(1) if (m := _BODY.search(doc)) else doc for doc in docs)


def x4_problems(path: Path) -> list[str]:
    """What an EPUB for the Xteink X4 must not have (spec section 9, criterion 7): progressive
    JPEGs, images over 480x800, and font, SVG, WebP or GIF files."""
    problems = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            suffix = posixpath.splitext(name)[1].lower()
            if suffix in _BANNED:
                problems.append(f"{name}: {suffix} file")
            elif suffix in {".jpg", ".jpeg", ".png"}:
                with Image.open(BytesIO(z.read(name))) as im:
                    if im.info.get("progressive"):
                        problems.append(f"{name}: progressive JPEG")
                    if im.width > 480 or im.height > 800:
                        problems.append(f"{name}: {im.width}x{im.height} is over 480x800")
    return problems
