import re
import socket

import pytest
from fixtures.links import link_dir

from eco.options import Options
from eco.pipeline import convert_file


@pytest.fixture
def offline(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", boom)


@pytest.fixture
def data_dir(tmp_path, models):
    """A data folder of its own that reads the installed models, so the books that the tests
    extract stay out of the cache of the person who runs them."""
    data = tmp_path / "data"
    data.mkdir()
    link_dir(data / "models", models)
    return data


def book_text(result):
    """The text of the book folder with the Markdown escapes removed and the white space joined."""
    markdown = (result.book_dir / "book.md").read_text(encoding="utf-8")
    return " ".join(re.sub(r"\\(.)", r"\1", markdown).split())


@pytest.mark.slow
def test_two_column_converts_offline_in_reading_order(fixtures_dir, data_dir, tmp_path, offline):
    path, texts = fixtures_dir["two_column"]
    result = convert_file(path, Options(), tmp_path / "out", data_dir=data_dir)
    assert result.outputs["epub"].exists()
    assert not [f for f in result.findings if f.kind == "page_failed"]
    flow = book_text(result)
    start = 0
    for text in texts:
        wanted = " ".join(text.split())
        start = flow.find(wanted, start)
        assert start >= 0, f"missing or out of order: {wanted[:40]!r}"
        start += len(wanted)


@pytest.mark.slow
def test_blank_middle_page_converts_offline(fixtures_dir, data_dir, tmp_path, offline):
    result = convert_file(fixtures_dir["blank"], Options(), tmp_path / "out", data_dir=data_dir)
    assert result.outputs["epub"].exists()
    skipped = [(f.page, f.kind) for f in result.findings if f.kind in ("blank_page", "page_failed")]
    assert skipped == [(2, "blank_page")]
    flow = book_text(result)
    assert "First page text." in flow
    assert "Third page text." in flow
