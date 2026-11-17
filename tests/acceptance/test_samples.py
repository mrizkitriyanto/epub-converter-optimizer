"""Acceptance criteria 1 to 8 of spec section 9, on the owner's books in `samples/`.

Run them on the owner's machine, with the AI models installed and nothing else heavy running:

    uv run pytest -m acceptance -v -s

Each book is converted once per session by `python -m eco convert` in a subprocess, and the tests
read the result. The run is cold: it gets a data folder of its own, with the installed models linked
in, so no cached extraction can fake the time or the RAM and the owner's own cache stays as it is.
The pages of a criterion are cut out of the book's `book.md` by its page markers.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from metrics import (
    code_blocks,
    epub_text,
    headings,
    pages,
    sequence_scores,
    word_recall,
    words,
    x4_problems,
)

from eco.bookfolder import load_source

pytestmark = pytest.mark.acceptance

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
TIMEOUT = 3600  # seconds: a conversion that takes longer is killed, so a hang cannot stall the run
FOUR_GIB = 4 * 2**30

# Forensic, PDF page 106. The book lists three `icat` commands there; the layout model cuts the
# listing in two, so these two lines are one code block (spec section 9 asks for it) and the third
# command, `icat image.raw 267 > super-updater57.exe_`, is a code block of its own.
ICAT = [
    "$ icat image.raw 68 > photo.jpg_",
    "$ icat image.raw 34 > customerlist.xls_",
]
# Malware, Listing 11-1: the page break (PDF pages 268 and 269) cuts it into two parts of 5 lines.
# The book draws its numbered call-outs with these private-use glyphs.
CALL_OUT_1, CALL_OUT_2 = chr(0xF075), chr(0xF076)
LISTING_11_1 = [
    [
        "100014A0 WlxLoggedOutSAS",
        "100014A0 push esi",
        "100014A1 push edi",
        '100014A2 push offset aWlxloggedout_0 ; "WlxLoggedOutSAS"',
        f"100014A7 call Call_msgina_dll_function {CALL_OUT_1}",
    ],
    [
        "...",
        "100014FB push eax ; Args",
        '100014FC push offset aUSDSPSOpS ;"U: %s D: %s P: %s OP: %s"',
        '10001501 push offset aDRIVERS ; "drivers\\tcpudp.sys"',
        f"10001503 call Log_To_File {CALL_OUT_2}",
    ],
]


@dataclass
class Conversion:
    epub: Path
    book: Path | None  # the extracted book folder; an EPUB input has none
    seconds: float
    peak_bytes: int | None  # None where the OS cannot tell (Windows)

    @property
    def markdown(self) -> str:
        return load_source(self.book).markdown


def sample(pattern: str) -> Path:
    found = sorted(SAMPLES.glob(pattern))
    if not found:
        pytest.skip(f"samples/{pattern} is missing")
    return found[0]


def run_timed(cmd: list[str], log: Path) -> tuple[int, float, int | None]:
    """Run `cmd` with its output in `log`; return its exit code, seconds and peak RSS in bytes.

    The peak comes from `os.wait4`, the rusage of this child alone. `RUSAGE_CHILDREN` would give
    the largest child of the whole session, so a small book would inherit the peak of a big one.
    """
    start = time.monotonic()
    with log.open("wb") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
        killer = threading.Timer(TIMEOUT, proc.kill)
        killer.start()
        try:
            if hasattr(os, "wait4"):
                _, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
                peak = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)  # bytes, KiB
            else:
                proc.wait()
                peak = None
        finally:
            killer.cancel()
    return proc.returncode, time.monotonic() - start, peak


@pytest.fixture(scope="session")
def convert(tmp_path_factory, models):
    def run(source: Path) -> Conversion:
        work = tmp_path_factory.mktemp("convert")
        data, out, log = work / "data", work / "out", work / "eco.log"
        data.mkdir()
        (data / "models").symlink_to(models, target_is_directory=True)
        cmd = [sys.executable, "-m", "eco", "convert", str(source)]
        cmd += ["--data", str(data), "-o", str(out)]
        code, seconds, peak = run_timed(cmd, log)
        if code != 0:
            how = f"was killed by {signal.Signals(-code).name}" if code < 0 else f"exited {code}"
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-15:])
            pytest.fail(
                f"eco convert {source.name} {how} after {seconds:.0f} s. End of {log}:\n{tail}",
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
    if conversion.peak_bytes is None:
        pytest.skip("the peak RAM of a child is measured with os.wait4, which Windows lacks")
    gib = conversion.peak_bytes / 2**30
    print(f"{label}: peak RAM {gib:.2f} GiB (limit 4)")
    assert conversion.peak_bytes <= FOUR_GIB, f"peak RAM {gib:.2f} GiB, the limit is 4 GiB"


def test_ac1_threat_hunting_text_matches_the_publisher_epub(threat_hunting):
    truth = words(epub_text(sample("foundationsofthreathunting.epub")))
    out = words(threat_hunting.markdown)
    precision, recall = sequence_scores(truth, out)
    print(f"AC1: precision {precision:.4f}, recall {recall:.4f} (limit 0.99 each)")
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
    print(f"AC2: {bicara.seconds:.0f} s (limit 900)")
    assert bicara.seconds <= 900, f"{bicara.seconds:.0f} s, the limit is 900 s"


def test_ac2_bicara_peak_ram(bicara):
    check_peak_ram("AC2", bicara)


def test_ac3_forensic_icat_block_has_exactly_the_2_lines(forensic):
    blocks = code_blocks(pages(forensic.markdown, 105, 117))
    with_icat = [b for b in blocks if any("icat" in line for line in b)]
    assert ICAT in blocks, f"code blocks with icat on pages 105 to 117: {with_icat}"


def test_ac3_malware_listing_11_1_lines_are_whole(malware):
    blocks = code_blocks(pages(malware.markdown, 262, 274))
    missing = [part for part in LISTING_11_1 if part not in blocks]
    near = [b for b in blocks if any("100014" in line for line in b)]
    assert not missing, f"missing: {missing}\ncode blocks with 100014 on pages 262 to 274: {near}"


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


def test_ac7_x4_epub_has_no_progressive_jpeg_big_image_or_banned_file(publisher_epub):
    problems = x4_problems(publisher_epub.epub)
    assert not problems, "\n".join(problems)


def test_ac8_optimized_publisher_epub_is_at_most_1_mb(publisher_epub):
    size = publisher_epub.epub.stat().st_size
    print(f"AC8: {size / 1_000_000:.2f} MB (limit 1)")
    assert size <= 1_000_000, f"{size / 1_000_000:.2f} MB, the limit is 1 MB"
