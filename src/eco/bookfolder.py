import html
import json
import re
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path

from eco.book import Block, Book
from eco.events import Finding

_FRONT_MATTER_KEYS = ("title", "author", "language", "source", "cover")
_FRONT_MATTER = re.compile(r"---\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)
_MD_SPECIAL = re.compile(r"[\\`*_\[\]<>#|&]")
_LINE_START_LIST = re.compile(r"^(\d+)([.)])")
_LINE_START_MARK = re.compile(r"^[-+=~]")


@dataclass
class BookSource:
    meta: dict[str, str]
    markdown: str  # body without the front matter
    base_dir: Path


def write_book(book: Book, folder: Path, findings: list[Finding]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    front = [
        f"{key}: {json.dumps(getattr(book, key), ensure_ascii=False)}" for key in _FRONT_MATTER_KEYS
    ]
    chunks = [("front", "\n".join(["---", *front, "---"]))]
    footnotes: list[tuple[int, str]] = []  # (level of the section they belong to, text)
    section_level = 7  # before the first heading: flushed by any heading
    page = 0
    for block in book.blocks:
        if block.kind == "footnote":
            footnotes.append((section_level, block.text))
            continue
        if block.kind == "heading":
            level = min(max(block.level, 1), 6)
            chunks.extend(("footnote", _footnote(t)) for lv, t in footnotes if lv >= level)
            footnotes = [fn for fn in footnotes if fn[0] < level]
            section_level = level
        if block.page > 0 and block.page != page:
            page = block.page
            chunks.append(("page", f"<!-- page: {page} -->"))
        chunks.append((block.kind, _render(block)))
    chunks.extend(("footnote", _footnote(text)) for _, text in footnotes)

    out = chunks[0][1]
    for (prev, _), (kind, text) in pairwise(chunks):
        out += ("\n" if prev == kind == "list_item" else "\n\n") + text
    path = folder / "book.md"
    path.write_text(out + "\n", encoding="utf-8")
    write_report(folder, findings)
    return path


def write_report(folder: Path, findings: list[Finding]) -> None:
    (folder / "report.json").write_text(
        json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_report(folder: Path) -> list[Finding]:
    path = folder / "report.json"
    if not path.is_file():
        return []
    return [Finding(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def load_source(path: Path) -> BookSource:
    if path.is_dir():
        md_path, base_dir = path / "book.md", path
    else:
        md_path, base_dir = path, path.parent
    text = md_path.read_text(encoding="utf-8-sig")
    meta: dict[str, str] = {}
    if match := _FRONT_MATTER.match(text):
        meta = _parse_front_matter(match.group(1) or "")
        text = text[match.end() :].lstrip("\n")
    meta.setdefault("title", path.stem)
    return BookSource(meta, text, base_dir)


def _parse_front_matter(raw: str) -> dict[str, str]:
    meta = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            continue
        value = value.strip()
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        meta[key.strip()] = parsed if isinstance(parsed, str) else value
    return meta


def _render(block: Block) -> str:
    if block.kind == "table":
        body = "\n".join(line for line in block.html.splitlines() if line.strip())
        return f"<!-- table-image: {block.image} -->\n{body}" if block.image else body
    if block.image:  # picture, formula or code cropped to an image
        alt = " ".join(block.text.split()) or block.kind
        if block.caption:
            return (
                f'<figure><img src="{html.escape(block.image)}" alt="{html.escape(alt)}"/>'
                f"<figcaption>{html.escape(' '.join(block.caption.split()))}</figcaption></figure>"
            )
        return f"![{_md(alt)}]({block.image})"
    if block.kind == "heading":
        title = _md(" ".join(block.text.split()), block.markdown)
        return "#" * min(max(block.level, 1), 6) + " " + title
    if block.kind == "list_item":
        return "- " + _md(block.text, block.markdown).replace("\n", "\n  ")
    if block.kind == "code":
        return _fenced(block.text)
    return _md(block.text, block.markdown)  # paragraph, plus kinds the format does not list


def _footnote(text: str) -> str:
    return f'<p class="footnote">{html.escape(" ".join(text.split()))}</p>'


def escape_md(text: str) -> str:
    """Backslash the characters Markdown reads as markup, for text inside a line."""
    return _MD_SPECIAL.sub(r"\\\g<0>", text)


def _md(text: str, escaped: bool = False) -> str:
    """`escaped` text is Markdown already (see Block.markdown): only its line starts are guarded."""
    lines = []
    for line in text.split("\n"):
        line = line.strip() if escaped else escape_md(line.strip())
        line = _LINE_START_LIST.sub(r"\1\\\2", line)
        lines.append(_LINE_START_MARK.sub(r"\\\g<0>", line))
    return "\n".join(lines)


def _fenced(text: str) -> str:
    if "```" not in text:
        fence = "```"
    elif "~~~" not in text:
        fence = "~~~"
    else:
        fence = "`" * (max(len(run) for run in re.findall(r"`+", text)) + 1)
    return f"{fence}\n{text}\n{fence}"
