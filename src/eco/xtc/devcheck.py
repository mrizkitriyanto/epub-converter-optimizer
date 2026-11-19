"""Build files used to check Xteink firmware behavior on a real device."""

import argparse
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from eco.bookfolder import BookSource
from eco.epub.builder import build_epub
from eco.xtc.codec import encode_xtg, encode_xth
from eco.xtc.container import Chapter, write_container

WIDTH, HEIGHT = 480, 800
LEVELS = (255, 170, 85, 0)
LABELS = ("white", "light gray", "dark gray", "black")


def _png(path: Path) -> None:
    Image.new("RGB", (160, 100), (80, 140, 200)).save(path, "PNG")


def _jpeg(path: Path) -> None:
    Image.new("RGB", (160, 100), (200, 120, 60)).save(path, "JPEG", quality=85, progressive=False)


def _label(image: Image.Image, xy: tuple[int, int], text: str, fill: int) -> None:
    mask = Image.new("1", image.size)
    ImageDraw.Draw(mask).text(xy, text, fill=1)
    image.paste(fill, mask=mask)


def _pages() -> list[Image.Image]:
    ramp = Image.new("L", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(ramp)
    bar_width = WIDTH // len(LEVELS)
    for number, (level, label) in enumerate(zip(LEVELS, LABELS)):
        left = number * bar_width
        right = WIDTH if number == len(LEVELS) - 1 else left + bar_width
        draw.rectangle((left, 0, right - 1, HEIGHT - 1), fill=level)
        _label(ramp, (left + 8, 12), label, 0 if level >= 170 else 255)

    pages = [ramp]
    for number, text in ((2, "Chapter Two"), (3, "Chapter Three")):
        page = Image.new("1", (WIDTH, HEIGHT), 1)
        ImageDraw.Draw(page).text((32, 32), f"Page {number}: {text}", fill=0)
        pages.append(page.convert("L"))
    return pages


def _container(pages: list[Image.Image], *, hq: bool) -> bytes:
    encode = encode_xth if hq else encode_xtg
    chapters = [
        Chapter(title, number, number) for number, title in enumerate(("One", "Two", "Three"))
    ]
    return write_container(
        [
            encode(page if hq else page.point(lambda value: 255 if value >= 128 else 0))
            for page in pages
        ],
        hq=hq,
        width=WIDTH,
        height=HEIGHT,
        title="eco device check",
        author="eco",
        language="en",
        chapters=chapters,
        created=0,
    )


def _epub(path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="eco-device-check-") as raw:
        source = Path(raw)
        _jpeg(source / "baseline.jpg")
        _png(source / "sample.png")
        paragraphs = "\n\n".join(
            f"Paragraph {number}. " + "device check text " * 60 for number in range(140)
        )
        markdown = f"""# CSS checks

```text
{"x" * 160}
```

| One | Two | Three | Four |
| --- | --- | --- | --- |
| A | B | C | D |

![Baseline JPEG](baseline.jpg)

![PNG](sample.png)

# Large chapter

{paragraphs}
"""
        book = BookSource(
            {"title": "eco CSS check", "author": "eco", "language": "en"},
            markdown,
            source,
        )
        build_epub(book, path, device="x4")


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = _pages()
    (out_dir / "gray-ramp.xtch").write_bytes(_container(pages, hq=True))
    (out_dir / "chapters.xtc").write_bytes(_container(pages, hq=False))
    _epub(out_dir / "css-check.epub")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    build(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
