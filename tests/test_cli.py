import subprocess
import sys
from pathlib import Path

import pytest

from eco import __version__
from eco.cli import main
from eco.pdf.pages import pdf_metadata


def convert(tmp_path, *args):
    return main(["convert", *map(str, args), "--data", str(tmp_path / "d")])


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"eco {__version__}"


def test_version_does_not_load_the_pipeline():
    code = "import sys; from eco.cli import main; main(['--version']); sys.exit('eco.pipeline' in sys.modules)"
    assert (
        subprocess.run([sys.executable, "-c", code], capture_output=True, check=False).returncode
        == 0
    )


def test_no_command_is_a_usage_error(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_landscape_needs_an_xteink_device(tmp_path, capsys):
    md = tmp_path / "a.md"
    md.write_text("# A\n")
    assert convert(tmp_path, md, "--device", "general", "--landscape") == 2
    assert "--landscape" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.epub"))


def test_batch_continues_after_bad_file(tmp_path, capsys):
    good = tmp_path / "a b.md"
    good.write_text("# A\n\nx\n")
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    assert convert(tmp_path, good, bad, "-o", tmp_path / "o") == 1
    out = capsys.readouterr()
    assert (tmp_path / "o" / "a b.x4.epub").exists()
    assert "error: Not a readable PDF: broken.pdf" in out.err
    assert "Traceback" not in out.err


def test_password_pdf(tmp_path, capsys, encrypted_pdf):
    assert main(["convert", str(encrypted_pdf), "--data", str(tmp_path)]) == 1
    assert "password-protected" in capsys.readouterr().err


def test_missing_input_is_one_line(tmp_path, capsys):
    assert convert(tmp_path, tmp_path / "gone.md") == 1
    err = capsys.readouterr().err
    assert err.strip() == f"error: No such file or folder: {tmp_path / 'gone.md'}"


def test_drm_epub(tmp_path, capsys, drm_epub):
    assert convert(tmp_path, drm_epub) == 1
    assert "error: EPUB is DRM-protected: drm.epub" in capsys.readouterr().err


def test_models_missing_message(tmp_path, capsys, fixtures_dir):
    assert convert(tmp_path, fixtures_dir["blank"], "-o", tmp_path / "o") == 1
    assert "error: AI models are not installed. Run: eco setup" in capsys.readouterr().err


def test_folder_input_expands_without_recursion(tmp_path, capsys, small_book):
    folder = tmp_path / "in"
    (folder / "deep").mkdir(parents=True)
    (folder / "b.md").write_text("# B\n")
    (folder / "a.md").write_text("# A\n")
    (folder / "notes.txt").write_text("skip me")
    (folder / "deep" / "c.md").write_text("# C\n")
    (small_book).rename(folder / "s.book")
    assert convert(tmp_path, folder) == 0
    assert sorted(p.name for p in folder.glob("*.epub")) == ["a.x4.epub", "b.x4.epub", "s.x4.epub"]
    out = capsys.readouterr().out.splitlines()
    firsts = [line for line in out if line.endswith(".epub")]
    assert [Path(p).name for p in firsts] == ["a.x4.epub", "b.x4.epub", "s.x4.epub"]


def test_empty_folder_is_an_error(tmp_path, capsys):
    (tmp_path / "in").mkdir()
    assert convert(tmp_path, tmp_path / "in") == 1
    assert "error: No PDF, Markdown or EPUB files in" in capsys.readouterr().err


def test_same_stem_outputs_stay_distinct(tmp_path, fake_blocks, fixtures_dir):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(fixtures_dir["blank"].read_bytes())
    (tmp_path / "a.md").write_text("# A\n")
    assert convert(tmp_path, pdf, tmp_path / "a.md") == 0
    assert sorted(p.name for p in tmp_path.glob("*.epub")) == ["a.x4-1.epub", "a.x4.epub"]


def test_output_defaults_to_the_input_folder(tmp_path):
    md = tmp_path / "sub" / "a.md"
    md.parent.mkdir()
    md.write_text("# A\n")
    assert convert(tmp_path, md) == 0
    assert (tmp_path / "sub" / "a.x4.epub").exists()


def test_summary_and_progress(tmp_path, capsys, fake_blocks, fixtures_dir):
    fake_blocks.skip = {1}
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(fixtures_dir["blank"].read_bytes())
    assert convert(tmp_path, pdf, "-o", tmp_path / "o") == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert lines[0] == str(tmp_path / "o" / "b.x4.epub")
    assert lines[1].startswith("  size: ") and " KB -> " in lines[1] and lines[1].endswith(" KB")
    assert "blank_page 1" in out.out and "page_failed 1" in out.out
    assert "warning: page 1: This page could not be converted" in out.out
    assert "[read]" in out.err and "[layout]" in out.err and "[optimize]" in out.err
    assert "[layout] page 1/2" in out.err


def test_extract_copies_the_book_folder_and_never_overwrites(
    tmp_path, capsys, fake_blocks, fixtures_dir
):
    pdf = fixtures_dir["blank"]
    args = ["extract", str(pdf), "-o", str(tmp_path / "o"), "--data", str(tmp_path / "d")]
    assert main(args) == 0
    first = tmp_path / "o" / f"{pdf.stem}.book"
    assert capsys.readouterr().out.splitlines()[0] == str(first)
    assert (first / "book.md").is_file() and (first / "report.json").is_file()
    runs = len(fake_blocks.calls)
    (first / "book.md").write_text("edited")
    assert main(args) == 0
    assert len(fake_blocks.calls) == runs  # the second extraction came from the cache
    assert (first / "book.md").read_text() == "edited"
    assert (tmp_path / "o" / f"{pdf.stem}-1.book" / "book.md").read_text() != "edited"


def test_extract_default_folder_is_the_input_folder(tmp_path, fake_blocks, fixtures_dir):
    pdf = tmp_path / "in" / "x.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(fixtures_dir["blank"].read_bytes())
    assert main(["extract", str(pdf), "--data", str(tmp_path / "d")]) == 0
    assert (tmp_path / "in" / "x.book" / "book.md").is_file()


def test_extract_retitles_a_renamed_pdf_without_title(tmp_path, fake_blocks, fixtures_dir):
    assert "title" not in pdf_metadata(fixtures_dir["blank"])
    data = ["--data", str(tmp_path / "d")]
    for name in ("first", "second"):
        pdf = tmp_path / f"{name}.pdf"
        pdf.write_bytes(fixtures_dir["blank"].read_bytes())
        assert main(["extract", str(pdf), "-o", str(tmp_path / "o"), *data]) == 0
    md = (tmp_path / "o" / "second.book" / "book.md").read_text()
    assert md.splitlines()[1] == 'title: "second"'


def test_extract_error_is_one_line(tmp_path, capsys):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    assert main(["extract", str(bad), "--data", str(tmp_path / "d")]) == 1
    assert capsys.readouterr().err.strip().endswith("error: Not a readable PDF: broken.pdf")


@pytest.mark.parametrize("command", ["convert", "extract"])
def test_bad_data_folder_is_one_line(tmp_path, capsys, command):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert main([command, str(blocker), "--data", str(blocker / "d")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and len(err.splitlines()) == 1


def test_setup_error_that_no_retry_helps_is_one_line(monkeypatch, tmp_path, capsys):
    def refuse(**kwargs):
        raise PermissionError("no write access to the models folder")

    monkeypatch.setattr("eco.models._docling_download", refuse)
    assert main(["setup", "--yes", "--data", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert err == "error: no write access to the models folder\n"
