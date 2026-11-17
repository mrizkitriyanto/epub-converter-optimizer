from PIL import Image

from eco.book import Block
from eco.events import Finding
from eco.pdf.code import fix_code_blocks, reextract_code
from eco.pdf.pages import inspect_pdf


def test_reextract_with_cropbox_offset(fixtures_dir):
    path, lines, bbox = fixtures_dir["code"]
    info = inspect_pdf(path)[0]
    assert reextract_code(path, info, bbox).splitlines() == lines


def test_reextract_returns_none_without_chars(fixtures_dir):
    path, _, _ = fixtures_dir["code"]
    info = inspect_pdf(path)[0]
    assert reextract_code(path, info, (300.0, 400.0, 400.0, 500.0)) is None


def test_reextract_returns_none_on_scanned_page(fixtures_dir):
    path, _ = fixtures_dir["scanned"]
    info = inspect_pdf(path)[0]
    assert reextract_code(path, info, (50.0, 50.0, 300.0, 150.0)) is None


def test_fix_code_blocks_restores_text(fixtures_dir, tmp_path):
    path, lines, bbox = fixtures_dir["code"]
    pages = {1: inspect_pdf(path)[0]}
    code = Block("code", text="flattened code", page=1, bbox=bbox)
    prose = Block("paragraph", text="prose", page=1, bbox=(0.0, 0.0, 50.0, 10.0))
    no_bbox = Block("code", text="no box", page=1)
    off_page = Block("code", text="page 9", page=9, bbox=bbox)
    blocks = [prose, code, no_bbox, off_page]

    fixed, findings = fix_code_blocks(path, blocks, pages, tmp_path / "images")

    assert fixed[1].text.splitlines() == lines
    assert fixed[1].kind == "code"
    assert code.text == "flattened code"
    assert [fixed[0], fixed[2], fixed[3]] == [prose, no_bbox, off_page]
    assert findings == [Finding(1, "code_restored", "info", findings[0].message)]
    assert not (tmp_path / "images").exists()


def test_fix_code_blocks_keeps_text_when_nothing_better(fixtures_dir, tmp_path):
    path, lines, bbox = fixtures_dir["code"]
    pages = {1: inspect_pdf(path)[0]}
    same = Block("code", text="\n".join(lines), page=1, bbox=bbox)
    empty = Block("code", text="stays", page=1, bbox=(300.0, 400.0, 400.0, 500.0))

    fixed, findings = fix_code_blocks(path, [same, empty], pages, tmp_path)

    assert fixed == [same, empty]
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "code_not_restored", "warning")]


def test_fix_code_blocks_crops_scanned_page(fixtures_dir, tmp_path):
    path, _ = fixtures_dir["scanned"]
    pages = {1: inspect_pdf(path)[0]}
    bbox = (50.0, 50.0, 300.0, 150.0)
    blocks = [Block("code", text=f"code {n}", page=1, bbox=bbox) for n in (1, 2)]
    images_dir = tmp_path / "book" / "images"

    fixed, findings = fix_code_blocks(path, blocks, pages, images_dir)

    assert [(b.kind, b.image, b.text) for b in fixed] == [
        ("image", "images/p0001-code-1.png", "code 1"),
        ("image", "images/p0001-code-2.png", "code 2"),
    ]
    assert blocks[0].kind == "code"
    for name in ("p0001-code-1.png", "p0001-code-2.png"):
        assert Image.open(images_dir / name).size[0] > 0
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "code_as_image", "info")] * 2
