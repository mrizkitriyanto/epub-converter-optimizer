import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from importlib.metadata import version
from pathlib import Path

import pytest

from eco import __version__
from eco.bookfolder import load_source
from eco.cli import main
from eco.epub.builder import build_epub
from eco.models import MARKER
from eco.pdf.pages import pdf_metadata


def convert(tmp_path, *args):
    return main(["convert", *map(str, args), "--data", str(tmp_path / "d")])


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"eco {__version__}"


def test_focus_mode_embeds_bold_in_converted_epub(tmp_path):
    md = tmp_path / "reading.md"
    md.write_text("# Chapter\n\nHelloWorld", encoding="utf-8")
    out = tmp_path / "out"
    assert (
        convert(
            tmp_path,
            md,
            "--device",
            "general",
            "--focus-mode",
            "--focus-weight",
            "600",
            "-o",
            out,
        )
        == 0
    )
    [epub] = out.glob("*.epub")
    with zipfile.ZipFile(epub) as archive:
        chapter = next(name for name in archive.namelist() if name.endswith("ch001.xhtml"))
        root = ET.fromstring(archive.read(chapter))
    assert any(
        node.text == "Hell" and node.get("style") == "font-weight:600"
        for node in root.iter("{http://www.w3.org/1999/xhtml}b")
    )


def test_focus_mode_embeds_bold_when_input_is_epub(tmp_path):
    md = tmp_path / "reading.md"
    md.write_text("# Chapter\n\nHelloWorld", encoding="utf-8")
    source = tmp_path / "source.epub"
    build_epub(load_source(md), source, device="general")
    out = tmp_path / "out"
    assert convert(tmp_path, source, "--device", "general", "--focus-mode", "-o", out) == 0
    [epub] = out.glob("*.epub")
    with zipfile.ZipFile(epub) as archive:
        chapter = next(name for name in archive.namelist() if name.endswith("ch001.xhtml"))
        root = ET.fromstring(archive.read(chapter))
    assert any(node.text == "Hell" for node in root.iter("{http://www.w3.org/1999/xhtml}b"))


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
    assert (tmp_path / "o" / "a b.x4-pro.epub").exists()
    assert "error: Not a readable PDF: broken.pdf" in out.err
    assert "Traceback" not in out.err
    assert out.out.splitlines()[-1] == "1 converted, 1 failed: broken.pdf"


def test_password_pdf(tmp_path, capsys, encrypted_pdf):
    assert main(["convert", str(encrypted_pdf), "--data", str(tmp_path)]) == 1
    assert "password-protected" in capsys.readouterr().err


def test_missing_input_is_one_line(tmp_path, capsys):
    assert convert(tmp_path, tmp_path / "gone.md") == 1
    err = capsys.readouterr().err
    assert err.strip() == f"error: No such file or folder: {tmp_path / 'gone.md'}"


def test_a_book_md_that_antivirus_removed_is_one_plain_line(
    tmp_path, capsys, monkeypatch, fixtures_dir, fake_blocks
):
    monkeypatch.setattr(sys, "platform", "win32")
    write_text = Path.write_text

    def blocked(self, *args, **kwargs):
        if self.name == "book.md":
            raise OSError(22, "Invalid argument", str(self))
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", blocked)
    assert convert(tmp_path, fixtures_dir["blank"], "-o", tmp_path / "o") == 1
    err = capsys.readouterr().err
    [line] = [line for line in err.splitlines() if line.startswith("error: ")]
    assert "book.md. Antivirus software may have removed it" in line
    assert "Traceback" not in err


def test_a_book_md_that_antivirus_holds_when_read_is_one_plain_line(
    tmp_path, capsys, monkeypatch, fixtures_dir, fake_blocks
):
    monkeypatch.setattr(sys, "platform", "win32")
    read_text = Path.read_text

    def held(self, *args, **kwargs):
        if self.name == "book.md":
            raise OSError(22, "Invalid argument", str(self))
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", held)
    assert convert(tmp_path, fixtures_dir["blank"], "-o", tmp_path / "o") == 1
    err = capsys.readouterr().err
    [line] = [line for line in err.splitlines() if line.startswith("error: ")]
    assert line.startswith("error: Could not read ") and "book.md. Antivirus software may" in line
    assert "Traceback" not in err


def test_a_book_md_gone_right_after_the_extraction_is_one_plain_line(
    tmp_path, capsys, monkeypatch, fixtures_dir, fake_blocks
):
    read_text = Path.read_text

    def gone(self, *args, **kwargs):
        if self.name == "book.md":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", gone)
    assert convert(tmp_path, fixtures_dir["blank"], "-o", tmp_path / "o") == 1
    err = capsys.readouterr().err
    [line] = [line for line in err.splitlines() if line.startswith("error: ")]
    assert line.startswith("error: Could not find ") and "book.md. Antivirus software may" in line


def test_a_book_folder_of_the_user_without_book_md_is_the_usual_one_line_error(tmp_path, capsys):
    folder = tmp_path / "mine.book"
    folder.mkdir()
    assert convert(tmp_path, folder) == 1
    err = capsys.readouterr().err
    assert "error: " in err and "Antivirus" not in err


def test_drm_epub(tmp_path, capsys, drm_epub):
    assert convert(tmp_path, drm_epub) == 1
    assert "error: EPUB is DRM-protected: drm.epub" in capsys.readouterr().err


def test_models_missing_message(tmp_path, capsys, fixtures_dir):
    assert convert(tmp_path, fixtures_dir["blank"], "-o", tmp_path / "o") == 1
    assert "error: AI models are not installed. Run: eco setup" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["convert", "extract"])
def test_conversion_names_the_missing_vc_runtime(
    tmp_path, capsys, monkeypatch, fixtures_dir, platform_is, vc_message, command
):
    platform_is("win32")
    data = tmp_path / "d"
    (data / "models").mkdir(parents=True)
    (data / "models" / MARKER).write_text(version("docling"))  # the models are installed

    def convert(self, source, **kwargs):
        raise ImportError(
            "DLL load failed while importing onnxruntime_pybind11_state: "
            "The specified module could not be found."
        )

    monkeypatch.setattr("docling.document_converter.DocumentConverter.convert", convert)
    args = [command, str(fixtures_dir["blank"]), "-o", str(tmp_path / "o"), "--data", str(data)]
    assert main(args) == 1
    err = capsys.readouterr().err
    assert f"error: {vc_message}\n" in err and "Traceback" not in err


def test_folder_input_expands_without_recursion(tmp_path, capsys, small_book):
    folder = tmp_path / "in"
    (folder / "deep").mkdir(parents=True)
    (folder / "b.md").write_text("# B\n")
    (folder / "a.md").write_text("# A\n")
    (folder / "notes.txt").write_text("skip me")
    (folder / "deep" / "c.md").write_text("# C\n")
    (small_book).rename(folder / "s.book")
    assert convert(tmp_path, folder) == 0
    assert sorted(p.name for p in folder.glob("*.epub")) == [
        "a.x4-pro.epub",
        "b.x4-pro.epub",
        "s.x4-pro.epub",
    ]
    out = capsys.readouterr().out.splitlines()
    firsts = [line for line in out if line.endswith(".epub")]
    assert [Path(p).name for p in firsts] == ["a.x4-pro.epub", "b.x4-pro.epub", "s.x4-pro.epub"]


def test_empty_folder_is_an_error(tmp_path, capsys):
    (tmp_path / "in").mkdir()
    assert convert(tmp_path, tmp_path / "in") == 1
    assert "error: No PDF, Markdown or EPUB files in" in capsys.readouterr().err


def test_same_stem_outputs_stay_distinct(tmp_path, fake_blocks, fixtures_dir):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(fixtures_dir["blank"].read_bytes())
    (tmp_path / "a.md").write_text("# A\n")
    assert convert(tmp_path, pdf, tmp_path / "a.md") == 0
    assert sorted(p.name for p in tmp_path.glob("*.epub")) == ["a.x4-pro-1.epub", "a.x4-pro.epub"]


def test_output_defaults_to_the_input_folder(tmp_path):
    md = tmp_path / "sub" / "a.md"
    md.parent.mkdir()
    md.write_text("# A\n")
    assert convert(tmp_path, md) == 0
    assert (tmp_path / "sub" / "a.x4-pro.epub").exists()


def test_summary_and_progress(tmp_path, capsys, fake_blocks, fixtures_dir):
    fake_blocks.skip = {1}
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(fixtures_dir["blank"].read_bytes())
    assert convert(tmp_path, pdf, "-o", tmp_path / "o") == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert lines[0] == str(tmp_path / "o" / "b.x4-pro.epub")
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


def test_extract_says_plainly_when_antivirus_holds_the_cached_book_md(
    tmp_path, capsys, monkeypatch, fake_blocks, fixtures_dir
):
    monkeypatch.setattr(sys, "platform", "win32")
    read_text = Path.read_text

    def held(self, *args, **kwargs):
        if self.name == "book.md" and (tmp_path / "d") in self.parents:
            raise OSError(22, "Invalid argument", str(self))
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", held)
    args = ["extract", str(fixtures_dir["blank"]), "-o", str(tmp_path / "o")]
    assert main([*args, "--data", str(tmp_path / "d")]) == 1
    err = capsys.readouterr().err
    assert err.splitlines()[-1].startswith(f"error: Could not read {tmp_path / 'd'}")
    assert "book.md. Antivirus software may" in err and "Traceback" not in err


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


def test_folder_expansion_skips_earlier_outputs(tmp_path, capsys):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.md").write_text("# A\n")
    for _ in range(2):
        assert convert(tmp_path, folder) == 0
    assert sorted(p.name for p in folder.glob("*.epub")) == ["a.x4-pro.epub"]
    assert capsys.readouterr().out.count(".epub\n") == 2  # one conversion per run
    assert convert(tmp_path, folder / "a.x4-pro.epub") == 0  # named by the user: converted
    assert sorted(p.name for p in folder.glob("*.epub")) == ["a.x4-pro-1.epub", "a.x4-pro.epub"]


def test_folder_of_earlier_outputs_only_is_empty(tmp_path, capsys):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.general.epub").write_bytes(b"x")
    assert convert(tmp_path, folder) == 1
    assert "error: No PDF, Markdown or EPUB files in" in capsys.readouterr().err


def test_home_folder_is_expanded_in_inputs_and_output(home, tmp_path, monkeypatch):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.md").write_text("# A\n")
    assert convert(tmp_path, "~/in", "-o", "~/out") == 0
    assert (tmp_path / "out" / "a.x4-pro.epub").exists()
    assert not (work / "~").exists()


def test_extract_expands_the_home_folder(home, tmp_path, monkeypatch, fake_blocks, fixtures_dir):
    monkeypatch.chdir(tmp_path / "..")
    (tmp_path / "x.pdf").write_bytes(fixtures_dir["blank"].read_bytes())
    args = ["extract", "~/x.pdf", "-o", "~/out", "--data", str(tmp_path / "d")]
    assert main(args) == 0
    assert (tmp_path / "out" / "x.book" / "book.md").is_file()
    assert not (Path.cwd() / "~").exists()


def test_failure_while_printing_a_summary_does_not_stop_the_batch(tmp_path, capsys, monkeypatch):
    for name in ("a", "b"):
        (tmp_path / f"{name}.md").write_text("# T\n")
    calls = []

    def flaky(findings):
        calls.append(findings)
        if len(calls) == 1:
            raise UnicodeEncodeError("charmap", "x", 0, 1, "cannot encode")

    monkeypatch.setattr("eco.cli._print_findings", flaky)
    assert convert(tmp_path, tmp_path / "a.md", tmp_path / "b.md") == 1
    out = capsys.readouterr()
    assert sorted(p.name for p in tmp_path.glob("*.epub")) == ["a.x4-pro.epub", "b.x4-pro.epub"]
    assert out.out.splitlines()[-1] == "1 converted, 1 failed: a.md"


def test_clean_batch_summary_counts_files(tmp_path, capsys):
    for name in ("a", "b"):
        (tmp_path / f"{name}.md").write_text("# T\n")
    assert convert(tmp_path, tmp_path / "a.md", tmp_path / "b.md") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "2 converted"


def test_single_clean_file_has_no_batch_line(tmp_path, capsys):
    (tmp_path / "a.md").write_text("# T\n")
    assert convert(tmp_path, tmp_path / "a.md") == 0
    assert "converted" not in capsys.readouterr().out


def test_landscape_needs_page_images(tmp_path, capsys):
    md = tmp_path / "a.md"
    md.write_text("# A\n")
    assert convert(tmp_path, md, "--landscape") == 2
    assert "--mode pages" in capsys.readouterr().err


def test_xtc_needs_an_xteink_device(tmp_path, capsys):
    md = tmp_path / "a.md"
    md.write_text("# A\n")
    assert convert(tmp_path, md, "--device", "general", "--format", "epub,xtch") == 2
    assert "Xteink" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.epub"))
