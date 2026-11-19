from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal[
    "heading",
    "paragraph",
    "list_item",
    "code",
    "table",
    "image",
    "footnote",
    "formula",
    "picture",
    "contents",  # a page of contents or an index, until the fix stage turns it into text
]


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0
    page: int = 0
    bbox: tuple[float, float, float, float] | None = None  # top-left origin, PDF points, CropBox
    html: str = ""
    image: str = ""  # path relative to the book folder
    caption: str = ""
    ocr: bool = False
    markdown: bool = False  # text is Markdown that is already escaped (the EPUB reader)
    number: int | None = None  # a list item's own number (0 too), when its marker was a plain one


@dataclass
class Book:
    title: str
    author: str = ""
    language: str = "en"
    source: str = ""
    cover: str = ""
    blocks: list[Block] = field(default_factory=list)
