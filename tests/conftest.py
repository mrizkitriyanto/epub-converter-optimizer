import pytest
from fixtures.make import build_all, make_epub, make_messy_epub
from PIL import Image
from pypdf import PdfReader, PdfWriter

from eco.book import Block, Book
from eco.bookfolder import write_book
from eco.models import models_dir, models_ready
from eco.options import resolve_data_dir


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("pdf_fixtures"))


@pytest.fixture(scope="session")
def models():
    """The folder `eco setup` filled. The slow tests skip when it has not run."""
    d = models_dir(resolve_data_dir(None))
    if not models_ready(d):
        pytest.skip("AI models are not installed. Run: eco setup")
    return d


@pytest.fixture
def small_book(tmp_path):
    """A book folder: two chapters, a picture, a 6-column table with its image twin, a cover."""
    folder = tmp_path / "small.book"
    (folder / "images").mkdir(parents=True)
    for name, size in {
        "p0001-img-1.png": (80, 60),
        "p0002-table-1.png": (240, 90),
        "cover.png": (120, 160),
    }.items():
        Image.new("L", size, 180).save(folder / "images" / name)
    row = "".join(f"<td>{n}</td>" for n in range(1, 7))
    table = f"<table>\n<tr>{row.replace('td', 'th')}</tr>\n<tr>{row}</tr>\n</table>"
    blocks = [
        Block("heading", "One", level=1, page=1),
        Block("paragraph", "First chapter text.", page=1),
        Block("image", "A picture", image="images/p0001-img-1.png", page=1),
        Block("heading", "Two", level=1, page=2),
        Block("heading", "A section", level=2, page=2),
        Block("table", html=table, image="images/p0002-table-1.png", page=2),
        Block("paragraph", "Closing text.", page=3),
    ]
    book = Book(title="Small Book", author="A. Writer", cover="images/cover.png", blocks=blocks)
    write_book(book, folder, [])
    return folder


@pytest.fixture
def messy_epub(tmp_path):
    """A publisher EPUB with every problem the optimizer handles (see make_messy_epub)."""
    return make_messy_epub(tmp_path)


@pytest.fixture
def drm_epub(tmp_path):
    """An EPUB with an Adobe rights file next to its content."""
    files = {
        "META-INF/container.xml": (
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'
        ),
        "META-INF/rights.xml": '<rights xmlns="http://ns.adobe.com/adept"/>',
        "OEBPS/content.opf": '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"/>',
    }
    return make_epub(tmp_path / "drm.epub", files)


@pytest.fixture
def encrypted_pdf(fixtures_dir, tmp_path):
    """The blank fixture behind a user password. RC4 because pypdf's AES needs `cryptography`,
    and PDFium reports the same password error for either."""
    writer = PdfWriter(clone_from=PdfReader(fixtures_dir["blank"]))
    writer.encrypt("secret", algorithm="RC4-128")
    path = tmp_path / "locked.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path
