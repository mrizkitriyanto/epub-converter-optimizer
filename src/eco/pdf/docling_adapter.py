"""Docling adapter: runs Docling's PDF pipeline offline and maps its document to blocks.
Docling is imported inside `extract_blocks`, never at module level."""

from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from eco.book import Block
from eco.models import ModelsMissing, models_ready, offline_env

# Keep in step with the docling pin in pyproject.toml. The mapping below reads Docling's output
# as it is in this version.
DOCLING_VERSION = "2.150.1"

_installed = version("docling")
if _installed != DOCLING_VERSION:
    raise ImportError(
        f"eco is built for Docling {DOCLING_VERSION}, but {_installed} is installed. Reinstall eco."
    )

# Docling label -> block kind. Any other label with text (text, paragraph, reference, ...) is a
# paragraph. Captions are not listed: _to_blocks attaches them to their table or picture.
_KIND = {
    "title": "heading",
    "section_header": "heading",
    "list_item": "list_item",
    "code": "code",
    "formula": "formula",
    "picture": "picture",
    "chart": "picture",
    "table": "table",
    "document_index": "table",  # Docling's label for a contents page. The item is a table.
    "footnote": "footnote",
}


def _to_blocks(doc, scanned: frozenset[int]) -> list[Block]:
    """Map a docling_core DoclingDocument to blocks in reading order. Nothing in `doc` changes."""
    blocks = []
    for item, _ in doc.iterate_items():  # body layer only, so page headers and footers are out
        if item.label == "caption":
            continue
        kind = _KIND.get(item.label, "paragraph")
        text = getattr(item, "text", "")  # pictures and tables have none
        # Docling leaves a formula's text empty (the text layer goes to `orig`), and a formula,
        # picture or table is cropped from the page later, so those three are kept without text.
        if not text.strip() and kind not in ("formula", "picture", "table"):
            continue
        page, bbox = 0, None
        if item.prov:
            page = item.prov[0].page_no
            box = item.prov[0].bbox.to_top_left_origin(doc.pages[page].size.height)
            bbox = (box.l, box.t, box.r, box.b)
        level = 0
        if kind == "heading":
            level = 1 if item.label == "title" else item.level
        blocks.append(
            Block(
                kind,
                text,
                level=level,
                page=page,
                bbox=bbox,
                html=item.export_to_html(doc, add_caption=False) if kind == "table" else "",
                caption=item.caption_text(doc) if kind in ("table", "picture") else "",
                ocr=page in scanned,
            )
        )
    return blocks


def extract_blocks(
    pdf: Path,
    models: Path,
    *,
    first: int,
    last: int,
    ocr: str,
    on_page: Callable[[int], None],
    scanned: frozenset[int] = frozenset(),
) -> list[Block]:
    """Run Docling on pages `first` to `last` (1-based) and return their blocks.

    `on_page` gets the number of each page Docling finishes, in the order they finish. `scanned`
    holds the scanned pages: their blocks are marked as OCR. Raises ModelsMissing, before anything
    else, when `eco setup` has not run.
    """
    if not models_ready(models):
        raise ModelsMissing()
    with offline_env():
        # huggingface_hub reads the offline flags when it first loads, so import Docling in here.
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.datamodel.progress import PageCompletedProgress
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions(
            artifacts_path=models,
            do_ocr=ocr != "off",
            ocr_options=RapidOcrOptions(mode="full_page") if ocr == "force" else RapidOcrOptions(),
            do_table_structure=True,
            do_code_enrichment=False,
            do_formula_enrichment=False,
            generate_page_images=False,
            generate_picture_images=False,
        )
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

        def report(event):
            if isinstance(event, PageCompletedProgress):
                on_page(event.page_no)

        result = converter.convert(pdf, page_range=(first, last), progress_callback=report)
    return _to_blocks(result.document, scanned)
