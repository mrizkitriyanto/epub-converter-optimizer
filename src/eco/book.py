from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal[
    "heading", "paragraph", "list_item", "code", "table", "image", "footnote", "formula", "picture"
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
    number: int = 0  # a list item's own number, when its marker was a plain number


@dataclass
class Book:
    title: str
    author: str = ""
    language: str = "en"
    source: str = ""
    cover: str = ""
    blocks: list[Block] = field(default_factory=list)
