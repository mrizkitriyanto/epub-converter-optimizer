import pypdfium2 as pdfium


def test_code_pdf_has_offset_cropbox(fixtures_dir):
    pdf = pdfium.PdfDocument(fixtures_dir["code"][0])
    assert pdf[0].get_cropbox()[:2] == (54.0, 63.0)


def test_scanned_pdf_has_no_text(fixtures_dir):
    pdf = pdfium.PdfDocument(fixtures_dir["scanned"][0])
    assert pdf[0].get_textpage().get_text_range().strip() == ""


def test_blank_middle_has_three_pages(fixtures_dir):
    assert len(pdfium.PdfDocument(fixtures_dir["blank"])) == 3


def _boxes(path):
    """Char boxes in the block convention (top-left origin, relative to the CropBox)."""
    page = pdfium.PdfDocument(path)[0]
    left, _, _, top = page.get_cropbox()
    text = page.get_textpage()
    for i in range(text.count_chars()):
        x0, y0, x1, y1 = text.get_charbox(i)
        yield text.get_text_range(i, 1), (x0 - left, top - y1, x1 - left, top - y0)


def _inside(box, bbox):
    return box[0] >= bbox[0] and box[1] >= bbox[1] and box[2] <= bbox[2] and box[3] <= bbox[3]


def test_code_bbox_encloses_every_code_glyph_and_no_paragraph(fixtures_dir):
    path, lines, bbox = fixtures_dir["code"]
    boxes = [(c, b) for c, b in _boxes(path) if not c.isspace()]
    code_glyphs = sum(len(line.replace(" ", "")) for line in lines)
    inside = [b for _, b in boxes if _inside(b, bbox)]
    assert len(inside) == code_glyphs
    assert len(boxes) > code_glyphs
    assert all(b[3] < bbox[1] for _, b in boxes if not _inside(b, bbox))
    assert pdfium.PdfDocument(path)[0].get_cropbox() == (54.0, 63.0, 558.0, 729.0)


def test_formula_bbox_encloses_math_glyphs(fixtures_dir):
    path, bbox = fixtures_dir["formula"]
    boxes = [b for c, b in _boxes(path) if not c.isspace()]
    assert boxes and all(_inside(b, bbox) for b in boxes)


def test_two_column_texts_are_in_the_page_text(fixtures_dir):
    path, texts = fixtures_dir["two_column"]
    page_text = " ".join(pdfium.PdfDocument(path)[0].get_textpage().get_text_range().split())
    assert texts[0] == "Deep Fixture Paper"
    assert all(" ".join(t.split()) in page_text for t in texts)


def test_hyphen_pdf_has_line_end_hyphen_and_whole_word(fixtures_dir):
    text = pdfium.PdfDocument(fixtures_dir["hyphen"])[0].get_textpage().get_text_range()
    assert "seper–\r\ntinya" in text
    assert text.count("sepertinya") == 1


def test_two_column_right_text_starts_beside_the_left_intro(fixtures_dir):
    path, texts = fixtures_dir["two_column"]
    boxes = list(_boxes(path))
    chars = "".join(c for c, _ in boxes)
    intro_end = chars.rindex(texts[5][-20:]) + 19
    right_start = chars.index(texts[6][:20])
    # The right paragraph starts above the bottom of the left intro: not sortable by y alone.
    assert boxes[right_start][1][1] < boxes[intro_end][1][3]
