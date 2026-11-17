import pytest

from eco.pdf.docling_adapter import extract_blocks
from eco.pdf.pages import inspect_pdf
from eco.pdf.reading_order import fix_reading_order


@pytest.mark.slow
def test_two_column_and_code(fixtures_dir, models):
    blocks = extract_blocks(
        fixtures_dir["code"][0], models, first=1, last=1, ocr="auto", on_page=lambda n: None
    )
    assert any(b.kind == "code" for b in blocks)
    pages = []
    extract_blocks(
        fixtures_dir["scanned"][0], models, first=1, last=1, ocr="auto", on_page=pages.append
    )
    assert pages == [1]


@pytest.mark.slow
def test_code_bbox_matches_the_cropbox_convention(fixtures_dir, models):
    path, _, expected = fixtures_dir["code"]
    blocks = extract_blocks(path, models, first=1, last=1, ocr="auto", on_page=lambda n: None)
    code = next(b for b in blocks if b.kind == "code")
    # This guards the coordinate space. A wrong one shows up as an offset of 54 and 63 pt (the
    # CropBox offset) or a flipped y, not as a few points. It does not check the layout model's
    # exact box, which can come out a little looser than the text it surrounds.
    assert code.bbox == pytest.approx(expected, abs=10)


@pytest.mark.slow
def test_two_column_reads_in_order_after_the_fix(fixtures_dir, models):
    path, texts = fixtures_dir["two_column"]
    blocks = extract_blocks(path, models, first=1, last=1, ocr="auto", on_page=lambda n: None)
    blocks, _ = fix_reading_order(blocks, {1: inspect_pdf(path)[0]})
    # Docling may split or join lines, so look for each text in the whole flow, in order.
    flow = " ".join(" ".join(b.text for b in blocks).split())
    start = 0
    for text in texts:
        wanted = " ".join(text.split())
        start = flow.find(wanted, start)
        assert start >= 0, f"missing or out of order: {wanted[:40]!r}"
        start += len(wanted)
