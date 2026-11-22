"""Download names of the form `LANG - Title - Author`, from what a book says about itself."""

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from eco.epub.optimizer import _Doc
from eco.epub.zipio import check_expansion
from eco.pdf.text import sure_language

MAX_NAME = 150  # characters before the extension
_TEXT_LIMIT = 200_000  # enough text to tell the language
_DROP = re.compile(r'["?/\\*<>|\x00-\x1f\x7f]')
_DASHES = re.compile(r" - (?:- )+")
_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", re.IGNORECASE)
_JOINER = re.compile(r";|&|\b(?:and|dan)\b")
_SPLIT = re.compile(r"\s*(?:,|;|&|\band\b|\bdan\b)\s*")
_LANG = re.compile(r"[A-Za-z]{2,3}")


@dataclass(frozen=True)
class BookFacts:
    title: str
    authors: list[str]
    language: str  # what the metadata says; may be empty or wrong
    text: str


def facts_from_epub(path: Path) -> BookFacts:
    """Title, creators and language from the OPF, and the text of the spine in order. Raises on
    an EPUB that cannot be read."""
    with zipfile.ZipFile(path) as z:
        check_expansion(z, path.name)
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//{*}rootfile").get("full-path", "")
        opf = _Doc.parse(z.read(opf_path)).root
        meta = opf.find("{*}metadata")

        def texts(name: str) -> list[str]:
            found = meta.findall(f"{{*}}{name}") if meta is not None else []
            return [text for el in found if (text := " ".join("".join(el.itertext()).split()))]

        # a translator or editor listed as a creator is not an author: EPUB 2 says so in
        # opf:role, EPUB 3 in a <meta refines="#id" property="role">
        roles = {
            el.get("refines", "").lstrip("#"): (el.text or "").strip()
            for el in (meta.iterfind("{*}meta[@property='role']") if meta is not None else ())
        }
        creators = meta.findall("{*}creator") if meta is not None else []
        authors = [
            text
            for el in creators
            if (el.get("opf:role") or roles.get(el.get("id", ""), "")) in ("", "aut")
            and (text := " ".join("".join(el.itertext()).split()))
        ]

        hrefs = {item.get("id"): item.get("href") for item in opf.iterfind("{*}manifest/{*}item")}
        base = posixpath.dirname(opf_path)
        chunks: list[str] = []
        size = 0
        for ref in opf.iterfind("{*}spine/{*}itemref"):
            href = hrefs.get(ref.get("idref"))
            if not href or size >= _TEXT_LIMIT:
                continue
            name = posixpath.normpath(posixpath.join(base, unquote(href.partition("#")[0])))
            try:
                body = _Doc.parse(z.read(name)).root.find("{*}body")
            except (KeyError, ET.ParseError):
                continue
            if body is not None:
                chunk = " ".join("".join(body.itertext()).split())
                chunks.append(chunk)
                size += len(chunk)
    return BookFacts(
        next(iter(texts("title")), ""),
        authors,
        next(iter(texts("language")), ""),
        " ".join(chunks)[:_TEXT_LIMIT],
    )


def language_code(facts: BookFacts) -> tuple[str, str | None]:
    """The code a title and a download name start with (`ID`, `EN`, else the metadata's primary
    subtag, else ""), and the language the text decided (`id`, `en`, or None)."""
    lang = sure_language(facts.text)
    if lang:
        return lang.upper(), lang
    primary = facts.language.split("-")[0].split("_")[0]
    # undetermined, several, no linguistic content, uncoded: no language to show
    if not _LANG.fullmatch(primary) or primary.lower() in ("und", "mul", "zxx", "mis"):
        return "", None
    return primary.upper(), None


def titled(title: str, code: str) -> str:
    """`CODE - title`; the same title when there is no code or it already starts with it."""
    if not code or title.startswith(f"{code} - "):
        return title
    return f"{code} - {title}"


def library_name(facts: BookFacts) -> str | None:
    """`LANG - Title - Author` without an extension, safe as a Windows file name. The language
    comes from the text, then from the metadata, else it is left out; so is a missing author.
    None when no title is left."""
    code, _ = language_code(facts)
    raw_title = " ".join(facts.title.split())
    if code:
        raw_title = raw_title.removeprefix(f"{code} - ")
    authors = [" ".join(a.split()) for a in facts.authors if a.strip()]
    if not authors:
        head, sep, tail = raw_title.rpartition(" - ")
        words = tail.split()
        if sep and head and 2 <= len(words) <= 4 and all(w[0].isupper() for w in words):
            raw_title, authors = head, [tail]
    title = _clean(raw_title)
    if not title:
        return None
    author = _author(authors, " dkk." if code == "ID" else " et al.")
    parts = [code, title, author]
    name = " - ".join(p for p in parts if p)
    if len(name) > MAX_NAME:
        room = MAX_NAME - (len(name) - len(title))
        cut = title[: max(room, 0) + 1]
        cut = cut[: cut.rfind(" ")] if " " in cut else cut[:room]
        name = " - ".join(p for p in (code, _clean(cut), author) if p)[:MAX_NAME].rstrip(" -")
    return f"{name}_" if _RESERVED.fullmatch(name) else name


def _author(authors: list[str], marker: str) -> str:
    """The first author, turned round from `Last, First`, with `marker` when there are more."""
    if not authors:
        return ""
    if len(authors) > 1:
        return _clean(authors[0]) + marker
    one = authors[0]
    parts = [p for p in _SPLIT.split(one) if p]
    last_first = one.count(",") == 1 and len(parts) == 2 and not _JOINER.search(one)
    if last_first and len(parts[0].split()) == 1:
        return _clean(f"{parts[1]} {parts[0]}")
    if len(parts) > 1:
        return _clean(parts[0]) + marker
    return _clean(one)


def _clean(text: str) -> str:
    text = _DROP.sub("", text.replace(":", " - "))
    text = _DASHES.sub(" - ", " ".join(text.split()))
    return text.strip(" .-")
