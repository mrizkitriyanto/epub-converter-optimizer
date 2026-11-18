"""Acceptance criteria 1 to 8 of spec section 9, on the owner's books in `samples/`.

Run them on the owner's machine, with the AI models installed and nothing else heavy running:

    uv run pytest -m acceptance -v -s

Each book is converted once per session by `python -m eco convert` in a subprocess, and the tests
read the result. The run is cold: it gets a data folder of its own, with the installed models linked
in, so no cached extraction can fake the time or the RAM and the owner's own cache stays as it is.
The pages of a criterion are cut out of the book's `book.md` by its page markers.

Criterion 7 also runs EPUBCheck on every output. Set ECO_JAVA to the path of `java` and
ECO_EPUBCHECK_JAR to the path of `epubcheck.jar`; without them that part is skipped.

The books' own text that a test needs (a page transcript, code listings) is read from
`samples/ground-truth/` and is never kept in this public repo.
"""

import platform
import re
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from fixtures.links import link_dir
from metrics import (
    code_blocks,
    drop_section,
    epub_text,
    epubcheck_problems,
    epubcheck_tools,
    failure_reason,
    ground_truth_blocks,
    hardware,
    headings,
    pages,
    run_timed,
    sample,
    sequence_scores,
    time_verdict,
    word_recall,
    words,
    x4_problems,
)

from eco.bookfolder import load_source

pytestmark = pytest.mark.acceptance

TIMEOUT = 4 * 3600  # seconds: only stops a hang, a book takes hours on a slow laptop
FOUR_GIB = 4 * 2**30
LIMIT_SECONDS = 900  # AC2: 15 minutes, on an M3 Mac
BOOKS = ["threat_hunting", "bicara", "forensic", "malware", "resnet", "publisher_epub"]


@dataclass
class Conversion:
    epub: Path
    book: Path | None  # the extracted book folder; an EPUB input has none
    seconds: float
    peak_bytes: int  # the most RAM the conversion process held at once

    @property
    def markdown(self) -> str:
        return load_source(self.book).markdown


@pytest.fixture(scope="session")
def convert(tmp_path_factory, models):
    def run(source: Path) -> Conversion:
        work = tmp_path_factory.mktemp("convert")
        data, out, log = work / "data", work / "out", work / "eco.log"
        data.mkdir()
        link_dir(data / "models", models)
        cmd = [sys.executable, "-m", "eco", "convert", str(source)]
        cmd += ["--data", str(data), "-o", str(out)]
        code, seconds, peak = run_timed(cmd, log, TIMEOUT)
        if code != 0:
            how = f"was killed by {signal.Signals(-code).name}" if code < 0 else f"exited {code}"
            text = log.read_text(errors="replace")
            reason = failure_reason(text)
            tail = "\n".join(text.splitlines()[-15:])
            pytest.fail(
                f"eco convert {source.name} {how} after {seconds:.0f} s"
                + (f": {reason}" if reason else "")
                + f"\nEnd of {log}:\n{tail}",
                pytrace=False,
            )
        books = list((data / "cache").glob("*.book"))
        return Conversion(next(out.glob("*.epub")), books[0] if books else None, seconds, peak)

    return run


@pytest.fixture(scope="session")
def threat_hunting(convert):
    return convert(sample("foundationsofthreathunting.pdf"))


@pytest.fixture(scope="session")
def bicara(convert):
    return convert(sample("Bicara itu ada seninya*.pdf"))


@pytest.fixture(scope="session")
def forensic(convert):
    return convert(sample("Practical Forensic Imaging*.pdf"))


@pytest.fixture(scope="session")
def malware(convert):
    return convert(sample("Practical Malware Analysis*.pdf"))


@pytest.fixture(scope="session")
def resnet(convert):
    return convert(sample("public/arxiv-1512.03385v1.pdf"))


@pytest.fixture(scope="session")
def publisher_epub(convert):
    return convert(sample("foundationsofthreathunting.epub"))


def check_peak_ram(label: str, conversion: Conversion) -> None:
    gib = conversion.peak_bytes / 2**30
    print(f"{label}: peak RAM {gib:.2f} GiB (limit 4)")
    assert conversion.peak_bytes <= FOUR_GIB, f"peak RAM {gib:.2f} GiB, the limit is 4 GiB"


def sharing_a_line(expected: list[list[str]], blocks: list[list[str]]) -> list[list[str]]:
    """The code blocks that have a line of more than one word in common with the expected ones."""
    lines = {line for block in expected for line in block if " " in line}
    return [block for block in blocks if lines & set(block)]


def test_ac1_threat_hunting_text_matches_the_publisher_epub(threat_hunting):
    """The text of the output EPUB against the publisher's (R-65). The publisher EPUB has no index,
    so precision leaves the output's index section out and is printed both ways (Q-21)."""
    truth = words(epub_text(sample("foundationsofthreathunting.epub")))
    markup = epub_text(threat_hunting.epub)
    out, without_index = words(markup), words(drop_section(markup, "Index"))
    precision_all, recall = sequence_scores(truth, out)
    precision, _ = sequence_scores(truth, without_index)
    print(
        f"AC1: precision {precision:.4f} without the index ({precision_all:.4f} with its "
        f"{len(out) - len(without_index)} words), recall {recall:.4f} (limit 0.99 each)"
    )
    assert precision >= 0.99 and recall >= 0.99, f"precision {precision:.4f}, recall {recall:.4f}"


def test_ac2_bicara_page_87_word_recall(bicara):
    truth = words(sample("ground-truth/bicara-p87.txt").read_text(encoding="utf-8"))
    recall = word_recall(truth, words(pages(bicara.markdown, 87, 87)))
    print(f"AC2: page 87 word recall {recall:.4f} (limit 0.99)")
    assert recall >= 0.99, f"word recall {recall:.4f}"


def test_ac2_bicara_headings_on_pages_80_to_92_are_exact(bicara):
    text = sample("ground-truth/bicara-p80-92-headings.txt").read_text(encoding="utf-8")
    expected = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    assert len(expected) == 14, expected
    found = headings(pages(bicara.markdown, 80, 92))
    missing = [h for h in expected if h not in found]
    print(f"AC2: {len(expected) - len(missing)} of 14 headings exact")
    assert not missing, f"not exact: {missing}\nheadings found on pages 80 to 92: {found}"


def test_ac2_bicara_converts_in_15_minutes(bicara):
    where = hardware()
    print(f"AC2: {bicara.seconds:.0f} s (limit {LIMIT_SECONDS}) on {where}")
    verdict = time_verdict(bicara.seconds, LIMIT_SECONDS, platform.system(), platform.machine())
    if verdict == "skip":
        pytest.skip(
            f"{bicara.seconds:.0f} s is over {LIMIT_SECONDS} s, but that limit is for an M3 Mac "
            f"and the time is not comparable on {where}"
        )
    assert verdict == "pass", f"{bicara.seconds:.0f} s, the limit is {LIMIT_SECONDS} s ({where})"


def test_ac2_bicara_peak_ram(bicara):
    check_peak_ram("AC2", bicara)


def test_ac3_forensic_icat_block_has_exactly_the_2_lines(forensic):
    expected = ground_truth_blocks("forensic-p106-icat.txt")
    assert [len(block) for block in expected] == [2], expected
    blocks = code_blocks(pages(forensic.markdown, 105, 117))
    assert expected[0] in blocks, (
        f"expected {expected[0]}\n"
        f"code blocks on pages 105 to 117 that share a line with it: "
        f"{sharing_a_line(expected, blocks)}"
    )


def test_ac3_malware_listing_11_1_lines_are_whole(malware):
    expected = ground_truth_blocks("malware-p268-269-listing-11-1.txt")
    assert [len(part) for part in expected] == [5, 5], expected
    blocks = code_blocks(pages(malware.markdown, 262, 274))
    missing = [part for part in expected if part not in blocks]
    assert not missing, (
        f"missing: {missing}\n"
        f"code blocks on pages 262 to 274 that share a line with them: "
        f"{sharing_a_line(expected, blocks)}"
    )


def test_ac4_resnet_headings_run_title_abstract_introduction(resnet):
    found = headings(pages(resnet.markdown, 1, 4))
    wanted = ["Deep Residual", "Abstract", "1. Introduction"]
    at = [next((i for i, h in enumerate(found) if h.startswith(w)), None) for w in wanted]
    assert None not in at and at == sorted(at), f"headings on pages 1 to 4: {found}"


def test_ac5_resnet_formulas_on_page_3_are_images(resnet):
    images = re.findall(
        r"!\[formula\]\(images/p0003-formula-\d+\.png\)", pages(resnet.markdown, 3, 3)
    )
    print(f"AC5: {len(images)} formula images on page 3 (want 2)")
    assert len(images) == 2, f"formula images on page 3: {images}"


def test_ac6_malware_peak_ram(malware):
    check_peak_ram("AC6", malware)


@pytest.mark.parametrize("book", BOOKS)
def test_ac7_x4_output_has_no_banned_file_big_image_or_bad_mimetype(book, request):
    problems = x4_problems(request.getfixturevalue(book).epub)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("book", BOOKS)
def test_ac7_x4_output_passes_epubcheck(book, request):
    java, jar = epubcheck_tools()
    problems = epubcheck_problems(request.getfixturevalue(book).epub, java, jar)
    assert not problems, "\n".join(problems)


def test_ac8_optimized_publisher_epub_is_at_most_1_mb(publisher_epub):
    size = publisher_epub.epub.stat().st_size
    print(f"AC8: {size / 1_000_000:.2f} MB (limit 1)")
    assert size <= 1_000_000, f"{size / 1_000_000:.2f} MB, the limit is 1 MB"
