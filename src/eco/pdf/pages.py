"""Thin pypdfium2 layer. Page numbers are 1-based everywhere, like Docling's `page_no`.
Bounding boxes are `(x0, y0, x1, y1)` in points, top-left origin, relative to the CropBox."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image

Bbox = tuple[float, float, float, float]


class PdfOpenError(Exception):
    pass


@dataclass(frozen=True)
class PageInfo:
    number: int
    width: float
    height: float
    crop_x: float
    crop_y: float
    chars: int
    image_ratio: float

    @property
    def is_blank(self) -> bool:
        return self.chars == 0 and self.image_ratio == 0

    @property
    def is_scanned(self) -> bool:
        return self.chars < 10 and self.image_ratio > 0.6


@dataclass(frozen=True)
class Bookmark:
    title: str
    level: int
    page: int


@contextmanager
def _open(path: Path) -> Iterator[pdfium.PdfDocument]:
    try:
        pdf = pdfium.PdfDocument(path)
    except (pdfium.PdfiumError, OSError) as error:
        if getattr(error, "err_code", None) == pdfium_raw.FPDF_ERR_PASSWORD:
            raise PdfOpenError(f"PDF is password-protected: {path.name}") from error
        raise PdfOpenError(f"Not a readable PDF: {path.name}") from error
    try:
        yield pdf
    finally:
        pdf.close()


def image_bounds(page: pdfium.PdfPage) -> list[tuple[float, float, float, float]]:
    """The raster images of a page, as (left, bottom, right, top) in PDF page coordinates.

    PDFium gives an image inside a Form XObject its bounds without the matrix of the form object
    around it (the `cm` before its `Do`), so the matrix of each form around the image is applied,
    innermost first."""
    boxes = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        form = obj.container
        while form is not None:
            matrix = form.get_matrix()
            corners = [matrix.on_point(x, y) for x in (left, right) for y in (bottom, top)]
            xs, ys = [x for x, _ in corners], [y for _, y in corners]
            left, bottom, right, top = min(xs), min(ys), max(xs), max(ys)
            form = form.container
        boxes.append((left, bottom, right, top))
    return boxes


def inspect_pdf(path: Path) -> list[PageInfo]:
    infos = []
    with _open(path) as pdf:
        for index, page in enumerate(pdf):
            width, height = page.get_width(), page.get_height()
            crop_x, crop_y, _, _ = page.get_cropbox()
            image_area = 0.0
            for left, bottom, right, top in image_bounds(page):
                image_area += (right - left) * (top - bottom)
            textpage = page.get_textpage()
            infos.append(
                PageInfo(
                    number=index + 1,
                    width=width,
                    height=height,
                    crop_x=crop_x,
                    crop_y=crop_y,
                    chars=textpage.count_chars(),
                    image_ratio=min(1.0, image_area / (width * height)),
                )
            )
    return infos


def bookmarks(path: Path) -> list[Bookmark]:
    found = []
    with _open(path) as pdf:
        for item in pdf.get_toc(max_depth=6):
            dest = item.get_dest()
            index = dest.get_index() if dest else None
            if index is not None:
                found.append(Bookmark(item.get_title(), item.level, index + 1))
    return found


def pdf_metadata(path: Path) -> dict[str, str]:
    with _open(path) as pdf:
        raw = pdf.get_metadata_dict()
    values = {"title": raw.get("Title", ""), "author": raw.get("Author", "")}
    return {key: value.strip() for key, value in values.items() if value.strip()}


def page_count(path: Path) -> int:
    """The number of pages, without reading any of them."""
    with _open(path) as pdf:
        return len(pdf)


def render_page(path: Path, page: int, scale: float = 2.0, grayscale: bool = False) -> Image.Image:
    with _open(path) as pdf:
        image = pdf[page - 1].render(scale=scale, grayscale=grayscale).to_pil()
    image.load()
    return image


def render_page_fit(path: Path, page: int, width: int, max_height: int) -> Image.Image:
    """Page `page` drawn `width` px wide, or smaller when that would make it more than
    `max_height` px tall: a page 1 pt wide and 14,400 pt tall is not drawn 8,640,000 px tall (PDFium
    refuses a bitmap that size), so the picture of any page stays bounded."""
    with _open(path) as pdf:
        try:
            pdf_page = pdf[page - 1]
            w, h = pdf_page.get_size()
            scale = min(width / max(w, 1.0), max_height / max(h, 1.0))
            image = pdf_page.render(scale=scale).to_pil()
        except pdfium.PdfiumError as error:
            raise PdfOpenError(f"Page {page} cannot be drawn: {path.name}") from error
    image.load()
    return image


def crop(
    path: Path,
    page: int,
    bbox: Bbox,
    scale: float = 3.0,
    pad: float = 4.0,
    grayscale: bool = True,
) -> Image.Image:
    image = render_page(path, page, scale, grayscale)
    x0, y0, x1, y1 = bbox
    box = ((x0 - pad) * scale, (y0 - pad) * scale, (x1 + pad) * scale, (y1 + pad) * scale)
    left, top = max(0, round(box[0])), max(0, round(box[1]))
    right, bottom = min(image.width, round(box[2])), min(image.height, round(box[3]))
    return image.crop((left, top, right, bottom))


def to_pdfium_rect(info: PageInfo, bbox: Bbox) -> Bbox:
    """Move a CropBox-relative top-left bbox into PDF user space as `(left, bottom, right, top)`."""
    x0, y0, x1, y1 = bbox
    return (
        info.crop_x + x0,
        info.crop_y + info.height - y1,
        info.crop_x + x1,
        info.crop_y + info.height - y0,
    )
