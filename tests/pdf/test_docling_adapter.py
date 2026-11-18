import os
import subprocess
import sys
from importlib.metadata import version
from types import CodeType, SimpleNamespace

import pytest
from docling_core.types.doc import (
    BoundingBox,
    ContentLayer,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    GroupLabel,
    ProvenanceItem,
    RichTableCell,
    Size,
    TableCell,
    TableData,
)

from eco.book import Block
from eco.models import MARKER, ModelsMissing
from eco.pdf.docling_adapter import _keep_line_end_hyphens, _to_blocks, extract_blocks
from eco.pdf.text import dehyphenate

TEXT = "Some text."
# The same box twice: as Docling stores it (bottom-left origin, so top > bottom) and as a Block
# holds it on a 792 pt page (top-left origin).
DOCLING_BOX = (50, 700, 300, 650)
BLOCK_BOX = (50, 92, 300, 142)


def new_doc():
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=612, height=792))
    return doc


def prov(page=1, box=DOCLING_BOX):
    left, top, right, bottom = box
    bbox = BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.BOTTOMLEFT)
    return ProvenanceItem(page_no=page, charspan=(0, 0), bbox=bbox)


def table_data():
    def cell(text, row, col, header=False):
        return TableCell(
            text=text,
            start_row_offset_idx=row,
            end_row_offset_idx=row + 1,
            start_col_offset_idx=col,
            end_col_offset_idx=col + 1,
            column_header=header,
        )

    cells = [cell("H1", 0, 0, True), cell("H2", 0, 1, True), cell("a", 1, 0), cell("b", 1, 1)]
    return TableData(num_rows=2, num_cols=2, table_cells=cells)


def add_caption(doc, owner, text):
    """Docling's reading order adds a caption as a child of its table, picture or code item."""
    caption = doc.add_text(DocItemLabel.CAPTION, text, parent=owner, prov=prov())
    owner.captions.append(caption.get_ref())


def add_footnote(doc, owner, text, **kwargs):
    """Docling's reading order adds a footnote as a child of its table or picture."""
    kwargs.setdefault("prov", prov())
    footnote = doc.add_text(DocItemLabel.FOOTNOTE, text, parent=owner, **kwargs)
    owner.footnotes.append(footnote.get_ref())


def add_table_with_rich_cell(doc, text):
    """A table Docling found no grid in: its items go into a group under the table, and its one
    cell points to that group (readingorder_model._create_rich_cell_group). Returns the group."""
    table = doc.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[]), prov=prov())
    name = f"rich_cell_group_{len(doc.tables)}_0_0"
    group = doc.add_group(label=GroupLabel.UNSPECIFIED, name=name, parent=table)
    doc.add_text(DocItemLabel.TEXT, text, parent=group, prov=prov())
    cell = RichTableCell(
        text="",
        start_row_offset_idx=0,
        end_row_offset_idx=1,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        ref=group.get_ref(),
    )
    doc.add_table_cell(table_item=table, cell=cell)
    return group


def adds_text(label):
    return lambda doc, p: doc.add_text(label, TEXT, prov=p)


def adds_list_item(doc, p):
    return doc.add_list_item(TEXT, parent=doc.add_group(label=GroupLabel.LIST), prov=p)


@pytest.mark.parametrize(
    "add,kind,level",
    [
        pytest.param(lambda d, p: d.add_title(TEXT, prov=p), "heading", 1, id="title"),
        pytest.param(
            lambda d, p: d.add_heading(TEXT, level=3, prov=p), "heading", 3, id="section_header"
        ),
        pytest.param(adds_text(DocItemLabel.TEXT), "paragraph", 0, id="text"),
        pytest.param(adds_text(DocItemLabel.PARAGRAPH), "paragraph", 0, id="paragraph"),
        pytest.param(adds_text(DocItemLabel.REFERENCE), "paragraph", 0, id="reference"),
        pytest.param(adds_list_item, "list_item", 0, id="list_item"),
        pytest.param(lambda d, p: d.add_code(TEXT, prov=p), "code", 0, id="code"),
        pytest.param(adds_text(DocItemLabel.FOOTNOTE), "footnote", 0, id="footnote"),
        pytest.param(adds_text(DocItemLabel.HANDWRITTEN_TEXT), "paragraph", 0, id="other label"),
    ],
)
def test_text_labels(add, kind, level):
    doc = new_doc()
    add(doc, prov())
    assert _to_blocks(doc, frozenset()) == [Block(kind, TEXT, level=level, page=1, bbox=BLOCK_BOX)]


def test_picture_and_chart_become_pictures_and_keep_their_caption():
    doc = new_doc()
    picture = doc.add_picture(prov=prov())
    add_caption(doc, picture, "Figure 1: a photo.")
    chart = doc.add_picture(prov=prov())
    chart.label = DocItemLabel.CHART
    assert _to_blocks(doc, frozenset()) == [
        Block("picture", page=1, bbox=BLOCK_BOX, caption="Figure 1: a photo."),
        Block("picture", page=1, bbox=BLOCK_BOX),
    ]


def test_table_has_html_and_its_caption():
    doc = new_doc()
    table = doc.add_table(data=table_data(), prov=prov())
    add_caption(doc, table, "Table 1: numbers")
    [block] = _to_blocks(doc, frozenset())
    assert (block.kind, block.text, block.caption) == ("table", "", "Table 1: numbers")
    assert "<th>H1</th><th>H2</th>" in block.html and "<td>a</td><td>b</td>" in block.html


def test_document_index_is_a_table():
    doc = new_doc()
    doc.add_table(data=table_data(), label=DocItemLabel.DOCUMENT_INDEX, prov=prov())
    assert [b.kind for b in _to_blocks(doc, frozenset())] == ["table"]


def test_caption_that_a_code_block_owns_is_a_paragraph_right_after_the_code():
    # write_book renders a caption only for a block with an image, so a code block would lose it.
    doc = new_doc()
    code = doc.add_code("print(1)", prov=prov())
    add_caption(doc, code, "Listing 1: a call.")
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    assert _to_blocks(doc, frozenset()) == [
        Block("code", "print(1)", page=1, bbox=BLOCK_BOX),
        Block("paragraph", "Listing 1: a call.", page=1, bbox=BLOCK_BOX),
        Block("paragraph", TEXT, page=1, bbox=BLOCK_BOX),
    ]


def test_caption_without_an_owner_is_a_paragraph_in_its_place():
    doc = new_doc()
    doc.add_text(DocItemLabel.TEXT, "Before.", prov=prov())
    doc.add_text(DocItemLabel.CAPTION, "Figure 9: nothing to attach to", prov=prov())
    doc.add_text(DocItemLabel.TEXT, "After.", prov=prov())
    assert [(b.kind, b.text) for b in _to_blocks(doc, frozenset())] == [
        ("paragraph", "Before."),
        ("paragraph", "Figure 9: nothing to attach to"),
        ("paragraph", "After."),
    ]


def test_footnote_that_a_table_owns_appears_once():
    doc = new_doc()
    table = doc.add_table(data=table_data(), prov=prov())
    add_footnote(doc, table, "* a table note")
    doc.add_text(DocItemLabel.FOOTNOTE, "1 A free note.", prov=prov())
    blocks = _to_blocks(doc, frozenset())
    assert [(b.kind, b.text) for b in blocks] == [("table", ""), ("footnote", "1 A free note.")]
    # The table's own HTML carries the footnote it owns.
    assert "".join(b.text + b.html for b in blocks).count("* a table note") == 1


def test_text_in_a_table_cell_is_only_in_the_table_html():
    doc = new_doc()
    group = add_table_with_rich_cell(doc, "CELL TEXT")
    doc.add_heading("CELL HEAD", parent=group, prov=prov())
    add_table_with_rich_cell(doc, "OTHER TEXT")  # the rule holds for every table, not the first
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    blocks = _to_blocks(doc, frozenset())
    assert [(b.kind, b.text) for b in blocks] == [("table", ""), ("table", ""), ("paragraph", TEXT)]
    assert "CELL TEXT" in blocks[0].html and "CELL HEAD" in blocks[0].html
    assert "OTHER TEXT" in blocks[1].html


def test_picture_in_a_table_cell_is_a_picture_block_right_after_the_table():
    # The table HTML has no image, so the picture keeps a block of its own to be cropped later.
    doc = new_doc()
    group = add_table_with_rich_cell(doc, "CELL TEXT")
    doc.add_picture(parent=group, prov=prov(box=(100, 600, 200, 500)))
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    blocks = _to_blocks(doc, frozenset())
    assert [(b.kind, b.text) for b in blocks] == [
        ("table", ""),
        ("picture", ""),
        ("paragraph", TEXT),
    ]
    assert blocks[1].bbox == (100, 192, 200, 292)
    assert "CELL TEXT" in blocks[0].html


def test_footnote_that_a_picture_owns_comes_right_after_the_picture():
    # iterate_items goes into a picture only for its captions, so it never yields this footnote.
    doc = new_doc()
    picture = doc.add_picture(prov=prov())
    add_footnote(doc, picture, "A figure note.")
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    blocks = _to_blocks(doc, frozenset())
    assert [(b.kind, b.text) for b in blocks] == [
        ("picture", ""),
        ("footnote", "A figure note."),
        ("paragraph", TEXT),
    ]


def test_picture_footnote_has_its_own_page_and_box_or_the_pictures():
    doc = new_doc()
    doc.add_page(page_no=2, size=Size(width=500, height=700))
    picture = doc.add_picture(prov=prov())
    add_footnote(doc, picture, "Own place.", prov=prov(page=2, box=(10, 690, 110, 600)))
    add_footnote(doc, picture, "Picture's place.", prov=None)
    blocks = _to_blocks(doc, frozenset({2}))
    assert [b.text for b in blocks] == ["", "Own place.", "Picture's place."]
    _, own, borrowed = blocks
    assert (own.page, own.bbox, own.ocr) == (2, (10, 10, 110, 100), True)
    assert (borrowed.page, borrowed.bbox, borrowed.ocr) == (1, BLOCK_BOX, False)


def test_picture_footnote_without_text_is_skipped():
    doc = new_doc()
    picture = doc.add_picture(prov=prov())
    add_footnote(doc, picture, "")
    assert [b.kind for b in _to_blocks(doc, frozenset())] == ["picture"]


def test_empty_text_is_skipped_except_for_formulas_pictures_and_tables():
    doc = new_doc()
    doc.add_text(DocItemLabel.TEXT, "", prov=prov())
    # Docling keeps a formula's text-layer text in `orig` and leaves `text` empty. The formula
    # is cropped from the page later, so it must survive.
    doc.add_text(DocItemLabel.FORMULA, "", orig="y = F(x) + x", prov=prov())
    doc.add_picture(prov=prov())
    doc.add_table(data=TableData(num_rows=0, num_cols=0, table_cells=[]), prov=prov())
    assert _to_blocks(doc, frozenset()) == [
        Block("formula", page=1, bbox=BLOCK_BOX),
        Block("picture", page=1, bbox=BLOCK_BOX),
        Block("table", page=1, bbox=BLOCK_BOX),
    ]


def test_page_furniture_is_left_out():
    doc = new_doc()
    layer = ContentLayer.FURNITURE
    doc.add_text(DocItemLabel.PAGE_HEADER, "Running head", content_layer=layer, prov=prov())
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    assert [b.text for b in _to_blocks(doc, frozenset())] == [TEXT]


def test_page_and_bbox_come_from_the_items_own_page():
    doc = new_doc()
    doc.add_page(page_no=2, size=Size(width=500, height=700))
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov(page=2, box=(10, 690, 110, 600)))
    [block] = _to_blocks(doc, frozenset())
    assert (block.page, block.bbox) == (2, (10, 10, 110, 100))


def test_ocr_follows_the_scanned_pages():
    doc = new_doc()
    doc.add_page(page_no=2, size=Size(width=612, height=792))
    doc.add_text(DocItemLabel.TEXT, "one", prov=prov(page=1))
    doc.add_text(DocItemLabel.TEXT, "two", prov=prov(page=2))
    blocks = _to_blocks(doc, frozenset({2}))
    assert [(b.page, b.ocr) for b in blocks] == [(1, False), (2, True)]


def test_item_without_provenance_has_page_zero_and_no_bbox():
    doc = new_doc()
    doc.add_text(DocItemLabel.TEXT, TEXT)
    assert _to_blocks(doc, frozenset()) == [Block("paragraph", TEXT)]


def test_blocks_come_in_document_order():
    doc = new_doc()
    doc.add_title("A title", prov=prov())
    table = doc.add_table(data=table_data(), prov=prov())
    add_caption(doc, table, "Table 1: numbers")
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    assert [b.kind for b in _to_blocks(doc, frozenset())] == ["heading", "table", "paragraph"]


def test_document_is_not_changed():
    doc = new_doc()
    table = doc.add_table(data=table_data(), prov=prov())
    add_caption(doc, table, "Table 1: numbers")
    doc.add_title("A title", prov=prov())
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    before = doc.model_dump_json()
    _to_blocks(doc, frozenset({1}))
    assert doc.model_dump_json() == before


def test_models_missing(tmp_path):
    with pytest.raises(ModelsMissing, match="eco setup"):
        extract_blocks(
            tmp_path / "book.pdf",
            tmp_path,
            first=1,
            last=1,
            ocr="auto",
            on_page=lambda n: pytest.fail("converted"),
        )


PIPELINE_OPTIONS = {
    "artifacts_path",
    "do_ocr",
    "ocr_options",
    "do_table_structure",
    "do_code_enrichment",
    "do_formula_enrichment",
    "generate_page_images",
    "generate_picture_images",
}


def run_with_fake_convert(tmp_path, monkeypatch, pages_done, ocr="auto", scanned=frozenset()):
    """Call extract_blocks with Docling's `convert` replaced, so Docling never runs.

    The stand-in reports one event that is not about a page, then a PageCompletedProgress for each
    (page_no, success) in `pages_done`, and returns a document with one text on page 1. Returns the
    blocks, the page numbers that reached `on_page`, and what the stand-in was given.
    """
    # Docling takes seconds to import, so only the tests that call this load it.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.progress import (
        ConversionPhase,
        PageCompletedProgress,
        PhaseStartedProgress,
    )

    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / MARKER).write_text(version("docling"))
    doc = new_doc()
    doc.add_text(DocItemLabel.TEXT, TEXT, prov=prov())
    seen = {}

    def fake_convert(self, source, **kwargs):
        seen.update(
            source=source,
            kwargs=kwargs,
            options=self.format_to_options[InputFormat.PDF].pipeline_options,
            pipeline_cls=self.format_to_options[InputFormat.PDF].pipeline_cls,
            offline=(os.environ.get("HF_HUB_OFFLINE"), os.environ.get("TRANSFORMERS_OFFLINE")),
        )
        progress = kwargs["progress_callback"]
        base = {"document_index": 1, "document_name": "book"}
        progress(PhaseStartedProgress(phase=ConversionPhase.BUILD, **base))
        for completed, (page_no, success) in enumerate(pages_done, 1):
            progress(
                PageCompletedProgress(
                    page_no=page_no,
                    success=success,
                    completed_pages=completed,
                    total_pages=len(pages_done),
                    **base,
                )
            )
        return SimpleNamespace(document=doc)

    monkeypatch.setattr("docling.document_converter.DocumentConverter.convert", fake_convert)
    pages = []
    blocks = extract_blocks(
        tmp_path / "book.pdf",
        tmp_path,
        first=1,
        last=len(pages_done),
        ocr=ocr,
        on_page=pages.append,
        scanned=scanned,
    )
    return blocks, pages, seen


def test_only_pages_that_finished_are_reported(tmp_path, monkeypatch):
    _, pages, _ = run_with_fake_convert(tmp_path, monkeypatch, [(3, True), (2, False), (1, True)])
    assert pages == [3, 1]


@pytest.mark.parametrize("ocr", ["auto", "force", "off"])
def test_extract_blocks_runs_the_configured_pipeline_offline(tmp_path, monkeypatch, ocr):
    from docling.datamodel.pipeline_options import RapidOcrOptions

    pages_done = [(2, True), (1, True)]  # pages finish out of order
    blocks, pages, seen = run_with_fake_convert(
        tmp_path, monkeypatch, pages_done, ocr=ocr, scanned=frozenset({1})
    )

    assert pages == [2, 1]
    assert blocks == [Block("paragraph", TEXT, page=1, bbox=BLOCK_BOX, ocr=True)]
    assert seen["source"] == tmp_path / "book.pdf" and seen["kwargs"]["page_range"] == (1, 2)
    assert seen["offline"] == ("1", "1")
    assert "HF_HUB_OFFLINE" not in os.environ and "TRANSFORMERS_OFFLINE" not in os.environ
    options = seen["options"]
    assert options.model_fields_set >= PIPELINE_OPTIONS  # Docling ignores a misspelled option
    assert options.artifacts_path == tmp_path
    assert options.do_ocr is (ocr != "off")
    assert isinstance(options.ocr_options, RapidOcrOptions)
    assert options.ocr_options.mode == ("full_page" if ocr == "force" else "default")
    assert options.ocr_options.use_cls is False  # it turned upright lines upside down (R-71)
    assert options.ocr_options.detect_orientation is True
    assert options.ocr_options.rapidocr_params == {"Det.limit_side_len": 32}
    assert options.do_table_structure is True
    assert not (options.do_code_enrichment or options.do_formula_enrichment)
    assert not (options.generate_page_images or options.generate_picture_images)


@pytest.mark.parametrize(
    "lines, joined",
    [
        (["mereka masing-ma-", "sing pulang"], ["mereka masing-ma-\nsing pulang"]),
        (["the result-unprece-", "dented gain"], ["the result-unprece-\ndented gain"]),
        (["para guru-", "guru datang"], ["para guru-\nguru datang"]),
        (["hujan seper–", "tinya saya"], ["hujan seper–\ntinya saya"]),
        (["seperti se—", "karang"], ["seperti se—\nkarang"]),
        (["a hyphen-", "ated word"], ["a hyphen-\nated word"]),
        (["the end-of-", "season sale"], ["the end-of-\nseason sale"]),
        (["see example.org/a-", "b today"], ["see example.org/a-\nb today"]),
        (["a 512-", "byte page"], ["a 512-\nbyte page"]),
        (["Figure 4-", "2 shows"], ["Figure 4-\n2 shows"]),
        (["a mul-", "ti-", "line"], ["a mul-\nti-\nline"]),
        (["the end-of-", "(season)"], ["the end-of-\n(season)"]),
    ],
)
def test_a_line_end_hyphen_reaches_the_fix_stage_with_its_line_break(lines, joined):
    assert _keep_line_end_hyphens(lines) == joined


@pytest.mark.parametrize(
    "lines",
    [
        ["a dash -", "then more"],  # a dash after a space: Docling keeps it and adds a space
        ["first line", "second line"],
        ["no hyphen here", "2 apples"],
        ["one line only-"],
    ],
)
def test_other_line_ends_are_left_to_docling(lines):
    assert _keep_line_end_hyphens(lines) == lines


def built_pipeline(tmp_path, monkeypatch):
    """The pipeline class extract_blocks hands to Docling, with its models set up but not loaded:
    Docling's own _init_models is replaced by one that only makes the reading order options."""
    from docling.models.stages.reading_order.readingorder_model import ReadingOrderOptions
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

    _, _, seen = run_with_fake_convert(tmp_path, monkeypatch, [(1, True)])
    pipeline_cls = seen["pipeline_cls"]
    assert issubclass(pipeline_cls, StandardPdfPipeline)

    def init_models(self):
        self.reading_order_model = SimpleNamespace(options=ReadingOrderOptions())

    monkeypatch.setattr(StandardPdfPipeline, "_init_models", init_models)
    pipeline = object.__new__(pipeline_cls)
    pipeline._init_models()
    return pipeline


def names_used(code: CodeType) -> set[str]:
    """The attribute and global names a function's code uses, with those of the functions defined
    inside it."""
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, CodeType):
            names |= names_used(const)
    return names


def test_docling_runs_the_page_assembly_and_reading_order_that_the_pipeline_class_sets():
    """A rename or a moved call in Docling would leave eco's overrides unused, so the names and the
    calls are pinned."""
    from docling.models.stages.page_assemble.page_assemble_model import PageAssembleModel
    from docling.models.stages.reading_order.readingorder_model import ReadingOrderModel
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

    assert "assemble_model" in StandardPdfPipeline._create_run_ctx.__code__.co_names
    assert "reading_order_model" in StandardPdfPipeline._assemble_document.__code__.co_names
    assert "sanitize_text" in PageAssembleModel.__call__.__code__.co_names
    # the call sits in materialize_siblings, a function defined inside this method
    caller = ReadingOrderModel._readingorder_elements_to_docling_doc.__code__
    assert "_merge_elements" in names_used(caller)


def test_line_end_hyphens_go_through_docling_to_dehyphenate(tmp_path, monkeypatch):
    """Docling's real sanitize_text, then the fix stage's dehyphenate: the spec's rule decides."""
    pipeline = built_pipeline(tmp_path, monkeypatch)
    lines = ["mereka masing-ma-", "sing pulang, the result-unprece-", "dented gain, para guru-"]
    lines += ["guru datang, an up-to-", "date 8-", "bit word", "next line"]
    text = pipeline.assemble_model.sanitize_text(lines)
    assert text == (
        "mereka masing-ma-\nsing pulang, the result-unprece-\ndented gain, para guru-\n"
        "guru datang, an up-to-\ndate 8-\nbit word next line"
    )
    context = Block("paragraph", "masing-masing guru, up to date")
    out, _ = dehyphenate([Block("paragraph", text), context])
    assert out[0].text == (
        "mereka masing-masing pulang, the result-unprecedented gain, para guru-guru datang, "
        "an up-to-date 8-bit word next line"
    )


def test_the_reading_order_merge_keeps_a_hyphen_with_its_line_break(tmp_path, monkeypatch):
    """Docling merges a text that a page or column break cut, and drops a hyphen at its end."""
    order = built_pipeline(tmp_path, monkeypatch).reading_order_model
    box = BoundingBox(l=10, t=10, r=100, b=40)
    item = SimpleNamespace(text="para guru-", orig="para guru-", prov=[], hyperlink=None, label="t")
    rest = SimpleNamespace(text="guru datang.", page_no=2, cluster=SimpleNamespace(bbox=box))
    rest.label, rest.hyperlink = "t", None
    order._merge_elements(SimpleNamespace(), rest, item, 792.0)
    out, _ = dehyphenate([Block("paragraph", item.text), Block("paragraph", "guru itu")])
    assert out[0].text == "para guru-guru datang."


def test_import_does_not_load_docling():
    """Docling is slow to import, and huggingface_hub reads its offline flags when it loads."""
    code = (
        "import sys, eco.pdf.docling_adapter\n"
        "print(sorted({'docling', 'docling_core', 'huggingface_hub'} & set(sys.modules)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


def test_import_fails_for_another_docling_version():
    code = (
        "import importlib.metadata as m\n"
        "m.version = lambda name: '2.0.0'\n"
        "import eco.pdf.docling_adapter\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    message = result.stderr.strip().splitlines()[-1]
    assert "2.150.1" in message and "2.0.0" in message
