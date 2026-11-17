import pytest
from fixtures.make import build_all
from PIL import Image

from eco.book import Block, Book
from eco.bookfolder import write_book


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("pdf_fixtures"))


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
