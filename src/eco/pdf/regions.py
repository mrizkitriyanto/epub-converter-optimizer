"""Regions that cannot be reflowed become images: formulas, pictures, table twins, pages that
are mostly pictures, and text read by OCR from a picture on a page that has a text layer. Also the
cover and the screen-sized slices of `--mode pages`."""

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageOps

from eco.book import Block
from eco.epub.images import _is_line_art
from eco.events import Finding
from eco.pdf.pages import Bbox, PageInfo, _open, crop, render_page, to_pdfium_rect

_PAGE_IMAGE_AREA = 0.8
_PAGE_IMAGE_MAX_CHARS = 200
_JPEG_QUALITY = 92
_COVER_QUALITY = 90
_OVERLAP = 0.05
_TEXT_KINDS = ("paragraph", "heading", "list_item", "table", "footnote", "code")
_SLACK = 2.0  # pt: a block whose centre is this close to a picture is in it


def _save_png(im: Image.Image, images_dir: Path, stem: str) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    im.save(images_dir / f"{stem}.png")
    return f"images/{stem}.png"


def _save_by_content(im: Image.Image, images_dir: Path, stem: str) -> str:
    """Line art stays PNG; a photo as PNG would ship about 10x larger than a JPEG."""
    if _is_line_art(im):
        return _save_png(im, images_dir, stem)
    images_dir.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(images_dir / f"{stem}.jpg", "JPEG", quality=_JPEG_QUALITY)
    return f"images/{stem}.jpg"


def _picture_area(blocks: list[Block], info: PageInfo) -> float:
    """Share of the page covered by picture blocks, each clipped to the page."""
    area = 0.0
    for block in blocks:
        if block.kind == "picture" and block.bbox is not None:
            x0, y0, x1, y1 = block.bbox
            width = min(x1, info.width) - max(x0, 0.0)
            height = min(y1, info.height) - max(y0, 0.0)
            area += max(0.0, width) * max(0.0, height)
    return area / (info.width * info.height)


def _picture_boxes(document, info: PageInfo) -> list[Bbox]:
    """The raster pictures of a page, as CropBox-relative top-left boxes."""
    boxes = []
    for obj in document[info.number - 1].get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        top_edge, bottom_edge = info.crop_y + info.height - top, info.crop_y + info.height - bottom
        boxes.append((left - info.crop_x, top_edge, right - info.crop_x, bottom_edge))
    return boxes


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", re.sub(r"<[^>]*>", " ", text).lower())


def keep_picture_text_as_images(
    pdf: Path, blocks: list[Block], pages: dict[int, PageInfo], ocr: str
) -> tuple[list[Block], list[Finding]]:
    """On a page that has a text layer, text that Docling read by OCR from a picture becomes that
    picture (agent decision Q-22): OCR text carries reading errors and an invented structure
    (headings in the book's outline, a guessed table), while the picture is exact.

    A block is such text when its centre lies in a raster picture of the page and most of its
    words are missing from the text layer inside its box. The blocks of one picture become one
    `picture` block with the picture's box, in the place of the first, which the region pass then
    crops; none is added when Docling already gave that picture a block. Scanned pages keep their
    OCR text, and so does `--ocr force`, which asks for it."""
    if ocr != "auto":
        return blocks, []
    owner: dict[int, tuple[int, int]] = {}  # block index -> (page, picture index)
    boxes: dict[tuple[int, int], Bbox] = {}
    with _open(pdf) as document:
        for number in sorted({b.page for b in blocks}):
            info = pages.get(number)
            if info is None or info.is_scanned:
                continue
            pictures = _picture_boxes(document, info)
            if not pictures:
                continue
            textpage = document[number - 1].get_textpage()
            for index, block in enumerate(blocks):
                if block.page != number or block.bbox is None or block.kind not in _TEXT_KINDS:
                    continue
                x, y = (block.bbox[0] + block.bbox[2]) / 2, (block.bbox[1] + block.bbox[3]) / 2
                inside = [
                    k
                    for k, (x0, y0, x1, y1) in enumerate(pictures)
                    if x0 - _SLACK <= x <= x1 + _SLACK and y0 - _SLACK <= y <= y1 + _SLACK
                ]
                words = _words(block.text or block.html)
                if not inside or not words:
                    continue
                layer = set(_words(textpage.get_text_bounded(*to_pdfium_rect(info, block.bbox))))
                if 2 * sum(word in layer for word in words) < len(words):
                    owner[index] = (number, inside[0])
                    boxes[(number, inside[0])] = pictures[inside[0]]
    if not owner:
        return blocks, []

    def clip(page: int, box: Bbox) -> Bbox:
        info = pages[page]
        return (
            max(0.0, box[0]),
            max(0.0, box[1]),
            min(info.width, box[2]),
            min(info.height, box[3]),
        )

    def drawn(page: int, box: Bbox) -> bool:  # Docling already has a picture block for it
        return any(
            b.kind == "picture"
            and b.page == page
            and b.bbox is not None
            and box[0] - _SLACK <= (b.bbox[0] + b.bbox[2]) / 2 <= box[2] + _SLACK
            and box[1] - _SLACK <= (b.bbox[1] + b.bbox[3]) / 2 <= box[3] + _SLACK
            for b in blocks
        )

    out: list[Block] = []
    done: set[tuple[int, int]] = set()
    for index, block in enumerate(blocks):
        key = owner.get(index)
        if key is None:
            out.append(block)
        elif key not in done:
            done.add(key)
            if not drawn(key[0], boxes[key]):
                out.append(Block("picture", page=key[0], bbox=clip(key[0], boxes[key])))
    per_page = Counter(page for page, _ in done)
    findings = [
        Finding(
            page,
            "picture_text_as_image",
            "info",
            f"Text read by OCR from {n} picture{'s' if n > 1 else ''} kept as "
            f"{'those pictures' if n > 1 else 'the picture'}.",
        )
        for page, n in sorted(per_page.items())
    ]
    return out, findings


def materialize_regions(
    pdf: Path, blocks: list[Block], pages: dict[int, PageInfo], images_dir: Path
) -> tuple[list[Block], list[Finding]]:
    """Crop formula, picture and table blocks to images; a page that is mostly pictures becomes one
    image. Pictures, tables and pages are cropped in colour: the optimizer greys them for Xteink."""
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        by_page.setdefault(block.page, []).append(block)
    page_images = {
        number
        for number, info in pages.items()
        if info.chars < _PAGE_IMAGE_MAX_CHARS
        and _picture_area(by_page.get(number, []), info) > _PAGE_IMAGE_AREA
    }

    done: list[Block] = []
    findings: list[Finding] = []
    counts: Counter[tuple[int, str]] = Counter()
    page_image_done: set[int] = set()
    for block in blocks:
        info = pages.get(block.page)
        if block.page in page_images:
            if block.page not in page_image_done:
                page_image_done.add(block.page)
                stem = f"p{block.page:04d}-page"
                image = _save_by_content(render_page(pdf, block.page, 3.0), images_dir, stem)
                done.append(Block("image", f"Page {block.page}", page=block.page, image=image))
                findings.append(
                    Finding(block.page, "page_as_image", "info", "Picture page kept as one image.")
                )
        elif (
            info is None or block.bbox is None or block.kind not in ("formula", "picture", "table")
        ):
            done.append(block)
        else:
            counts[block.page, block.kind] += 1
            stem = f"p{block.page:04d}-{block.kind}-{counts[block.page, block.kind]}"
            if block.kind == "formula":
                image = _save_png(crop(pdf, block.page, block.bbox), images_dir, stem)
                done.append(replace(block, kind="image", text="formula", image=image))
                findings.append(
                    Finding(block.page, "formula_as_image", "info", "Formula kept as an image.")
                )
            elif block.kind == "picture":
                im = crop(pdf, block.page, block.bbox, grayscale=False)
                done.append(
                    replace(block, kind="image", image=_save_by_content(im, images_dir, stem))
                )
            else:
                im = crop(pdf, block.page, block.bbox, grayscale=False)
                done.append(replace(block, image=_save_png(im, images_dir, stem)))
    return done, findings


def render_cover(pdf: Path, images_dir: Path) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    render_page(pdf, 1, 2.0).convert("RGB").save(
        images_dir / "cover.jpg", "JPEG", quality=_COVER_QUALITY
    )
    return "images/cover.jpg"


def page_slices(
    pdf: Path, page: int, screen: tuple[int, int], landscape: bool = False
) -> list[Image.Image]:
    """Cut a page into screen-sized slices that overlap by 5%. `landscape` slices for the screen
    turned on its side, then rotates each slice clockwise so it is stored upright."""
    width, height = (screen[1], screen[0]) if landscape else screen
    im = render_page(pdf, page, 3.0).convert("RGB")
    ink = ImageOps.invert(im.convert("L")).getbbox()
    if ink is None:
        return []
    im = im.crop(ink)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
    step = height - round(_OVERLAP * height)
    slices = []
    top = 0
    while True:
        bottom = min(top + height, im.height)
        slices.append(im.crop((0, top, im.width, bottom)))
        if bottom >= im.height:
            break
        top += step
    if landscape:
        slices = [s.transpose(Image.Transpose.ROTATE_270) for s in slices]
    return slices
