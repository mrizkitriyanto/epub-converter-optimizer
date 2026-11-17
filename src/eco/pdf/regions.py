"""Regions that cannot be reflowed become images: formulas, pictures, table twins and pages that
are mostly pictures. Also the cover and the screen-sized slices of `--mode pages`."""

from collections import Counter
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageOps

from eco.book import Block
from eco.epub.images import _is_line_art
from eco.events import Finding
from eco.pdf.pages import PageInfo, crop, render_page

_PAGE_IMAGE_AREA = 0.8
_PAGE_IMAGE_MAX_CHARS = 200
_JPEG_QUALITY = 92
_COVER_QUALITY = 90
_OVERLAP = 0.05


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
