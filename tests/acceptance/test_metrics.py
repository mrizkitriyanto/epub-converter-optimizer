"""Fast checks of the acceptance helpers, so a mistake in them shows on every run and not only
after an hour on the owner's samples."""

import re
import subprocess
import sys
import zipfile

import metrics
import pytest
from metrics import (
    code_blocks,
    epub_text,
    epubcheck_problems,
    epubcheck_tools,
    failure_reason,
    ground_truth_blocks,
    hardware,
    headings,
    pages,
    run_timed,
    sequence_scores,
    time_verdict,
    word_recall,
    words,
    x4_problems,
)

from eco.epub.optimizer import optimize_epub
from eco.options import Options


def seq(text):
    return text.split()


LETTERS = seq("a b c d e f g h")


def test_words_keep_the_text_and_drop_the_markup():
    text = (
        "<!-- page: 3 -->\n![formula](images/p0003-formula-1.png)\n"
        "Don't miss [the Café](http://x.org/a_b) &amp; <b>Ünï</b> 42."
    )
    assert words(text) == ["don't", "miss", "the", "café", "ünï", "42"]
    assert words(r"see \[1\](x) there") == ["see", "1", "x", "there"]  # how eco writes `[1](x)`


def test_identical_text_scores_one():
    assert sequence_scores(LETTERS, LETTERS) == (1.0, 1.0)


def test_extra_output_words_cost_precision_only():
    assert sequence_scores(LETTERS, seq("a b c x y d e f g h")) == (0.8, 1.0)


def test_a_missing_word_inside_the_span_costs_recall_only():
    assert sequence_scores(LETTERS, seq("a b c d f g h")) == (1.0, 0.875)


def test_truth_outside_the_matched_span_is_not_missed():
    assert sequence_scores(seq("x y z a b c d e f"), seq("a b c d e f")) == (1.0, 1.0)


def test_blocks_of_fewer_than_three_words_do_not_count():
    # only "c d e" is kept: 3 of 6 output words, all of the 3-word span it covers in the truth
    assert sequence_scores(seq("a b x c d e"), seq("a b y c d e")) == (0.5, 1.0)


def test_nothing_in_common_scores_zero():
    assert sequence_scores(seq("a b c"), seq("x y z")) == (0.0, 0.0)
    assert sequence_scores(seq("a b c"), []) == (0.0, 0.0)


def test_word_recall_is_the_share_of_the_page_found_in_order():
    assert word_recall(LETTERS, seq("a b c d f g h")) == 0.875
    assert word_recall(LETTERS, []) == 0.0


BOOK = """\
---
title: "T"
---

<!-- page: 1 -->

# Title

Some text.

<!-- page: 2 -->

## 1\\. Intro

```
# not a heading
$ ls    -l
```

<!-- page: 3 -->

![formula](images/p0003-formula-1.png)
"""


def test_readers_of_a_book_md():
    assert pages(BOOK, 2, 3).startswith("## 1")
    assert "Title" not in pages(BOOK, 2, 3) and "formula" not in pages(BOOK, 1, 2)
    assert headings(BOOK) == ["Title", "1. Intro"]
    assert code_blocks(BOOK) == [["# not a heading", "$ ls -l"]]


def test_epub_text_is_the_spine_bodies_in_order(messy_epub):
    text = epub_text(messy_epub)
    assert text.index("Chapter One") < text.index("Chapter&nbsp;Two")
    assert "<title>" not in text and "float:right" not in text


def test_x4_problems_finds_what_the_optimizer_removes(messy_epub, tmp_path):
    problems = "\n".join(x4_problems(messy_epub))
    for found in ("photo.jpg: progressive", "photo.jpg: 1650x835", ".gif", ".webp", ".svg", ".otf"):
        assert found in problems
    optimized = tmp_path / "x4.epub"
    optimize_epub(messy_epub, optimized, Options(device="x4"))
    assert x4_problems(optimized) == []


def zip_of(path, entries):
    """A zip with `entries`, pairs of a name and a compression, written in that order."""
    with zipfile.ZipFile(path, "w") as z:
        for name, compress_type in entries:
            data = b"application/epub+zip" if name == "mimetype" else b"<html/>"
            z.writestr(name, data, compress_type=compress_type)
    return path


def test_x4_problems_wants_mimetype_first_and_stored(tmp_path):
    stored, deflated = zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED
    good = zip_of(tmp_path / "good.epub", [("mimetype", stored), ("a.xhtml", deflated)])
    assert x4_problems(good) == []
    second = zip_of(tmp_path / "second.epub", [("a.xhtml", deflated), ("mimetype", stored)])
    assert x4_problems(second) == ["mimetype is not the first entry"]
    packed = zip_of(tmp_path / "packed.epub", [("mimetype", deflated), ("a.xhtml", deflated)])
    assert x4_problems(packed) == ["mimetype is not STORED"]
    without = zip_of(tmp_path / "without.epub", [("a.xhtml", deflated)])
    assert x4_problems(without) == ["mimetype is not the first entry"]
    assert x4_problems(zip_of(tmp_path / "empty.epub", [])) == ["mimetype is not the first entry"]


MIB = 2**20


def test_run_timed_measures_the_peak_ram_of_the_child_that_does_the_work(tmp_path):
    log = tmp_path / "child.log"
    code = f"data = bytearray(b'x') * {300 * MIB}; print('touched', len(data))"
    exit_code, seconds, peak = run_timed([sys.executable, "-c", code], log, timeout=120)
    assert exit_code == 0 and seconds > 0
    assert "touched" in log.read_text()
    assert 300_000_000 <= peak < 2 * 2**30, f"{peak / MIB:.0f} MiB"


def test_run_timed_kills_a_child_that_outlives_the_timeout(tmp_path):
    code = "import time; time.sleep(120)"
    exit_code, seconds, _ = run_timed([sys.executable, "-c", code], tmp_path / "hang.log", 1)
    assert exit_code != 0 and seconds < 60


@pytest.mark.parametrize(
    ("seconds", "system", "machine", "verdict"),
    [
        (900, "Windows", "AMD64", "pass"),
        (900, "Darwin", "arm64", "pass"),
        (901, "Darwin", "arm64", "fail"),
        (901, "Darwin", "x86_64", "skip"),
        (3000, "Windows", "AMD64", "skip"),
        (3000, "Linux", "aarch64", "skip"),
    ],
)
def test_ac2_time_is_a_failure_only_on_the_machine_the_limit_is_defined_for(
    seconds, system, machine, verdict
):
    assert time_verdict(seconds, 900, system, machine) == verdict


def test_hardware_names_the_cpu_and_the_ram():
    assert re.fullmatch(r".+, \d+\.\d GiB RAM", hardware()), hardware()


def fake_epubcheck(monkeypatch, code, stdout="", stderr=""):
    """Stand in for the EPUBCheck process: it exits with `code` and prints the two streams."""

    def run(cmd, **kwargs):
        run.cmd = cmd
        return subprocess.CompletedProcess(cmd, code, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return run


def test_epubcheck_problems_are_its_error_and_fatal_lines(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    fatal = f'FATAL(RSC-016): {epub}/OPS/ch2.xhtml(8,6): Fatal Error while parsing file: x "</p>".'
    error = f'ERROR(RSC-005): {epub}/OPS/content.opf(1,62): Error while parsing file: "package"'
    warning = f"WARNING(OPF-014): {epub}/OPS/ch1.xhtml(3,1): The page uses scripting."
    summary = "Messages: 1 fatal / 1 error / 1 warning / 0 infos\n\nEPUBCheck completed\n"
    errors = f"{warning}\n{fatal}\n{error}\n\nCheck finished with errors\n"
    run = fake_epubcheck(monkeypatch, 1, summary, errors)
    assert epubcheck_problems(epub, "java", "epubcheck.jar") == [fatal, error]
    assert run.cmd == ["java", "-jar", "epubcheck.jar", str(epub)]
    fake_epubcheck(monkeypatch, 0, "No errors or warnings detected.\n", f"{warning}\n")
    assert epubcheck_problems(epub, "java", "epubcheck.jar") == []


def test_a_failed_epubcheck_without_an_error_line_is_a_problem(monkeypatch, tmp_path):
    crash = "Exception in thread main java.lang.OutOfMemoryError: Java heap space"
    fake_epubcheck(monkeypatch, 2, "", crash)
    [problem] = epubcheck_problems(tmp_path / "book.epub", "java", "epubcheck.jar")
    assert "exited 2" in problem and "OutOfMemoryError" in problem


def test_epubcheck_is_skipped_until_java_and_the_jar_are_set(monkeypatch, tmp_path):
    monkeypatch.delenv("ECO_JAVA", raising=False)
    monkeypatch.delenv("ECO_EPUBCHECK_JAR", raising=False)
    with pytest.raises(pytest.skip.Exception, match="ECO_JAVA and ECO_EPUBCHECK_JAR"):
        epubcheck_tools()
    monkeypatch.setenv("ECO_JAVA", "java")
    with pytest.raises(pytest.skip.Exception, match="ECO_JAVA and ECO_EPUBCHECK_JAR"):
        epubcheck_tools()
    monkeypatch.setenv("ECO_EPUBCHECK_JAR", "epubcheck.jar")
    assert epubcheck_tools() == ("java", "epubcheck.jar")


def test_epubcheck_accepts_what_the_optimizer_writes_for_the_x4(messy_epub, tmp_path):
    java, jar = epubcheck_tools()
    optimized = tmp_path / "x4.epub"
    optimize_epub(messy_epub, optimized, Options(device="x4"))
    assert epubcheck_problems(optimized, java, jar) == []


def test_epubcheck_finds_what_is_wrong_with_an_epub(drm_epub):
    java, jar = epubcheck_tools()
    problems = epubcheck_problems(drm_epub, java, jar)
    assert problems and all(p.startswith(("ERROR(", "FATAL(")) for p in problems)


def test_ground_truth_blocks_are_the_runs_of_lines_between_blank_lines(monkeypatch, tmp_path):
    (tmp_path / "ground-truth").mkdir()
    glyph = chr(0xF075)  # the private-use call-out glyph of a listing must survive as it is
    text = f"a   b\n  c {glyph}\n\n\nd\n"
    (tmp_path / "ground-truth" / "x.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(metrics, "SAMPLES", tmp_path)
    assert ground_truth_blocks("x.txt") == [["a b", f"c {glyph}"], ["d"]]


def test_a_missing_ground_truth_file_skips_the_test_and_names_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", tmp_path)
    with pytest.raises(pytest.skip.Exception, match=r"samples/ground-truth/x\.txt is missing"):
        ground_truth_blocks("x.txt")


def test_the_reason_of_a_failed_conversion_is_its_error_lines():
    log = "[layout] page 9/9\n[fix]\nerror: Could not read book.md. Antivirus software may\n"
    log += "0 converted, 1 failed: x.pdf\n"
    assert failure_reason(log) == "Could not read book.md. Antivirus software may"
    assert failure_reason("Traceback (most recent call last):\nKeyError: 1\n") == ""
