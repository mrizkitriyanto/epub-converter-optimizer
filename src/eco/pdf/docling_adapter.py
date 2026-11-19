"""Docling adapter: runs Docling's PDF pipeline offline and maps its document to blocks.
Docling is imported inside `extract_blocks`, never at module level."""

import re
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

# Docling label -> block kind. Any other label with text (text, paragraph, reference, caption, ...)
# is a paragraph. _to_blocks moves a caption into the table or picture that owns it.
_KIND = {
    "title": "heading",
    "section_header": "heading",
    "list_item": "list_item",
    "code": "code",
    "formula": "formula",
    "picture": "picture",
    "chart": "picture",
    "table": "table",
    # Docling's label for a page of contents or an index. The item is a table; the fix stage
    # reads it again from the text layer (contents.py), or keeps the table on a scanned page.
    "document_index": "contents",
    "footnote": "footnote",
}


_NUMBER_MARKER = re.compile(r"(\d+)[.)]")
_LINE_END_HYPHEN = re.compile(r"\w[-–—]$")
# RapidOCR's line classifier turned some upright lines of a scanned book upside down, and Docling's
# check of the whole region reads a badly read one again at 90, 180 and 270 degrees instead. Its
# detector scales a crop up until the short side is 736 px, which split a one-line heading into
# overlapping pieces ("1.1 Respons s yang"); 32 leaves each crop at its own size.
_OCR = {"use_cls": False, "detect_orientation": True, "rapidocr_params": {"Det.limit_side_len": 32}}


def _keep_line_end_hyphens(lines: list[str]) -> list[str]:
    """Join each line that ends in a hyphen, en dash or em dash after a word to the next line,
    keeping the dash and the line break.

    Docling joins the lines of a block and drops every hyphen that ends a line between two words,
    so `guru-` and `guru` became `guruguru` and `end-of-` and `season` became `end-ofseason`.
    Kept as `guru-\\nguru`, the split reaches the fix stage, whose dehyphenate decides it by the
    spec's rule. Every other line end is left to Docling.
    """
    out: list[str] = []
    for line in lines:
        if out and _LINE_END_HYPHEN.search(out[-1]):
            out[-1] += "\n" + line
        else:
            out.append(line)
    return out


def _position(doc, item):
    """The page and top-left bbox of an item's first provenance. Page 0 and no bbox without one."""
    if not item.prov:
        return 0, None
    prov = item.prov[0]
    box = prov.bbox.to_top_left_origin(doc.pages[prov.page_no].size.height)
    return prov.page_no, (box.l, box.t, box.r, box.b)


def _picture_footnotes(doc, picture, scanned: frozenset[int]) -> list[Block]:
    """The footnotes a picture owns, as blocks. iterate_items goes into a picture only for its
    captions, so it never yields them. A footnote without a place of its own takes the picture's."""
    blocks = []
    for ref in picture.footnotes:
        note = ref.resolve(doc)
        if note.text.strip():
            page, bbox = _position(doc, note if note.prov else picture)
            blocks.append(Block("footnote", note.text, page=page, bbox=bbox, ocr=page in scanned))
    return blocks


def _to_blocks(doc, scanned: frozenset[int]) -> list[Block]:
    """Map a docling_core DoclingDocument to blocks in reading order. Nothing in `doc` changes."""
    # The HTML of a table already holds the text of its cells, its footnotes and its captions, so
    # nothing under a table is a block of its own. A picture in a cell is the exception: HTML has
    # no image, so it keeps a block to be cropped. Form fields in a cell (the extract_form_fields
    # option, which eco leaves off) are not in the HTML, so turning that on needs a new rule here.
    in_table = {
        item.self_ref
        for table in doc.tables
        for item, _ in doc.iterate_items(root=table)
        if item is not table and _KIND.get(item.label) != "picture"
    }
    # The text of a caption that a table or picture owns goes into that block. Any other caption
    # (one that belongs to a code block, or to nothing) is a paragraph.
    owned_captions = {ref.cref for owner in (*doc.tables, *doc.pictures) for ref in owner.captions}
    blocks = []
    for item, _ in doc.iterate_items():  # body layer only, so page headers and footers are out
        if item.self_ref in in_table or item.self_ref in owned_captions:
            continue
        kind = _KIND.get(item.label, "paragraph")
        text = getattr(item, "text", "")  # pictures and tables have none
        # Docling leaves a formula's text empty (the text layer goes to `orig`), and a formula,
        # picture or table is cropped from the page later, so those three are kept without text.
        if not text.strip() and kind not in ("formula", "picture", "table", "contents"):
            continue
        page, bbox = _position(doc, item)
        tabular = kind in ("table", "contents")
        level, number = 0, None
        if kind == "heading":
            level = 1 if item.label == "title" else item.level
        elif kind == "list_item" and item.enumerated and item.marker:
            # "3." or "3)" is the item's number; "A.", "(i)" and the like stay at the start
            if found := _NUMBER_MARKER.fullmatch(item.marker.strip()):
                number = int(found[1])
            else:
                text = f"{item.marker.strip()} {text}"
        blocks.append(
            Block(
                kind,
                text,
                level=level,
                page=page,
                bbox=bbox,
                html=item.export_to_html(doc, add_caption=False) if tabular else "",
                caption=item.caption_text(doc) if tabular or kind == "picture" else "",
                ocr=page in scanned,
                number=number,
            )
        )
        if kind == "picture":
            blocks.extend(_picture_footnotes(doc, item, scanned))
    return blocks


def _pipeline_class():
    """Docling's PDF pipeline, changed in the two places where Docling joins a hyphen at a line
    end: the page assembly applies `_keep_line_end_hyphens` first, and the reading order keeps the
    hyphen and a line break when it merges a text that a page or column break cut. Docling is
    loaded by then: extract_blocks calls this inside offline_env."""
    from docling.models.stages.page_assemble.page_assemble_model import (
        PageAssembleModel,
        PageAssembleOptions,
    )
    from docling.models.stages.reading_order.readingorder_model import ReadingOrderModel
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

    class Assemble(PageAssembleModel):
        def sanitize_text(self, lines):
            return super().sanitize_text(_keep_line_end_hyphens(lines))

    class ReadingOrder(ReadingOrderModel):
        def _merge_elements(self, element, merged_elem, new_item, page_height):
            if _LINE_END_HYPHEN.search(new_item.text):
                new_item.text += "\n"  # no longer ends in "-", so Docling joins with a space
            super()._merge_elements(element, merged_elem, new_item, page_height)

    class Pipeline(StandardPdfPipeline):
        def _init_models(self):
            super()._init_models()
            self.assemble_model = Assemble(options=PageAssembleOptions())
            self.reading_order_model = ReadingOrder(options=self.reading_order_model.options)

    return Pipeline


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

    `on_page` gets the number of each page Docling finishes without error, in the order they
    finish. A page that failed is not reported, so the caller can see which pages are missing.
    `scanned` holds the scanned pages: their blocks are marked as OCR. Raises ModelsMissing, before
    anything else, when `eco setup` has not run.
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
            ocr_options=(
                RapidOcrOptions(mode="full_page", **_OCR)
                if ocr == "force"
                else RapidOcrOptions(**_OCR)
            ),
            do_table_structure=True,
            do_code_enrichment=False,
            do_formula_enrichment=False,
            generate_page_images=False,
            generate_picture_images=False,
        )
        pdf_format = PdfFormatOption(pipeline_options=options, pipeline_cls=_pipeline_class())
        converter = DocumentConverter(format_options={InputFormat.PDF: pdf_format})

        def report(event):
            if isinstance(event, PageCompletedProgress) and event.success:
                on_page(event.page_no)

        result = converter.convert(pdf, page_range=(first, last), progress_callback=report)
    return _to_blocks(result.document, scanned)
