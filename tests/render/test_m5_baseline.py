"""M3's default XTC render, frozen before M5 changes the page style."""

import hashlib

from eco.bookfolder import load_source
from eco.render.pages import render_book
from eco.style import PageStyle


def test_m3_default_pages_are_unchanged(tmp_path):
    book = tmp_path / "baseline.md"
    book.write_text(
        "# One\n\nA calm reading page with café and numbers 123.\n\n# Two\n\nAnother paragraph.\n",
        encoding="utf-8",
    )
    rendered = render_book(load_source(book), device="x4", style=PageStyle(), view="xtc")
    assert [hashlib.sha256(page).hexdigest() for page in rendered.pages] == [
        "f5ff80f0724630e3a2aa66fcddc6f75ef9edaffa50eb70d36b1df1a863c148a6",
        "47bb2eb50d53b7964d459887bfcea6a19374af4f97a4f1a076ab430ad68e312c",
    ]
