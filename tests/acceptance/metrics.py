"""What the acceptance tests measure (spec section 9), the readers of the files they measure, and
the helpers that run a conversion and check what it wrote."""

import ctypes
import difflib
import html
import os
import platform
import posixpath
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import pytest
from PIL import Image

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
MIN_BLOCK = 3  # a run of fewer matching words is chance, not a copy
_BANNED = {".otf", ".ttf", ".woff", ".woff2", ".svg", ".webp", ".gif"}

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"(?<!\\)\[([^\]]*)\]\([^)]*\)")  # not the `\[1\](x)` that eco writes
_TAG = re.compile(r"<[^>]*>")
_WORD = re.compile(r"[A-Za-z0-9À-ɏ']+")
_PAGE = re.compile(r"<!-- page: (\d+) -->")
_FENCE = re.compile(r"^(`{3,}|~{3,})\n(.*?)\n\1$", re.DOTALL | re.MULTILINE)
_HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL)
_EPUB_NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "o": "http://www.idpf.org/2007/opf",
}


def words(text: str) -> list[str]:
    """Lowercase tokens of Markdown or XHTML: images, link targets and tags are not text."""
    text = _MD_IMAGE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    return _WORD.findall(html.unescape(text).lower())


def _matched(truth: list[str], out: list[str]) -> list[difflib.Match]:
    matcher = difflib.SequenceMatcher(None, truth, out, autojunk=False)
    return [m for m in matcher.get_matching_blocks() if m.size >= MIN_BLOCK]


def sequence_scores(truth: list[str], out: list[str]) -> tuple[float, float]:
    """(precision, recall) of `out` against `truth`, counting only runs of at least 3 words that
    both have in the same order. Precision is the share of `out` in such runs. Recall is the share
    of `truth` in such runs, between the first word that matched and the last."""
    blocks = _matched(truth, out)
    if not blocks:
        return 0.0, 0.0
    matched = sum(m.size for m in blocks)
    span = blocks[-1].a + blocks[-1].size - blocks[0].a
    return matched / len(out), matched / span


def word_recall(truth_page: list[str], out: list[str]) -> float:
    """The share of the words of a transcribed page that `out` has, in order."""
    return sum(m.size for m in _matched(truth_page, out)) / len(truth_page)


def pages(markdown: str, first: int, last: int) -> str:
    """The text of PDF pages `first` to `last` of a book.md, cut at its page markers."""
    parts = _PAGE.split(markdown)  # the front, then a page number and its text, again and again
    return "\n\n".join(
        text.strip()
        for number, text in zip(parts[1::2], parts[2::2])
        if first <= int(number) <= last
    )


def headings(markdown: str) -> list[str]:
    """The headings of a book.md outside code, with the Markdown escapes taken out."""
    return [
        " ".join(re.sub(r"\\(.)", r"\1", heading).split())
        for heading in _HEADING.findall(_FENCE.sub("", markdown))
    ]


def code_blocks(markdown: str) -> list[list[str]]:
    """The lines of each fenced code block, with each run of white space made into one space."""
    return [
        [" ".join(line.split()) for line in body.split("\n")]
        for _, body in _FENCE.findall(markdown)
    ]


def epub_text(path: Path) -> str:
    """The markup inside `<body>` of every spine document of an EPUB, in reading order."""
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", _EPUB_NS).get("full-path")
        opf = ET.fromstring(z.read(opf_path))
        hrefs = {i.get("id"): unquote(i.get("href")) for i in opf.iterfind(".//o:item", _EPUB_NS)}
        folder = posixpath.dirname(opf_path)
        docs = []
        for ref in opf.iterfind(".//o:itemref", _EPUB_NS):
            name = posixpath.normpath(posixpath.join(folder, hrefs[ref.get("idref")]))
            docs.append(z.read(name).decode("utf-8"))
    return "\n".join(m.group(1) if (m := _BODY.search(doc)) else doc for doc in docs)


def x4_problems(path: Path) -> list[str]:
    """What an EPUB for the Xteink X4 must not have (spec section 9, criterion 7): progressive
    JPEGs, images over 480x800, font, SVG, WebP or GIF files, and a `mimetype` entry that is not
    the first one or not stored."""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if names[:1] != ["mimetype"]:
            problems.append("mimetype is not the first entry")
        if "mimetype" in names and z.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            problems.append("mimetype is not STORED")
        for name in names:
            suffix = posixpath.splitext(name)[1].lower()
            if suffix in _BANNED:
                problems.append(f"{name}: {suffix} file")
            elif suffix in {".jpg", ".jpeg", ".png"}:
                with Image.open(BytesIO(z.read(name))) as im:
                    if im.info.get("progressive"):
                        problems.append(f"{name}: progressive JPEG")
                    if im.width > 480 or im.height > 800:
                        problems.append(f"{name}: {im.width}x{im.height} is over 480x800")
    return problems


class _MemoryCounters(ctypes.Structure):
    """PROCESS_MEMORY_COUNTERS of psapi.h (a DWORD is a c_ulong on Windows)."""

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_working_set(handle: int) -> int:
    """PeakWorkingSetSize in bytes of the process that `handle` stands for (Windows). The counters
    stay readable after the process has exited for as long as a handle to it is open."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_MemoryCounters),
        ctypes.c_ulong,
    ]
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(int(handle), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def run_timed(cmd: list[str], log: Path, timeout: float) -> tuple[int, float, int]:
    """Run `cmd` with its output in `log`; return its exit code, seconds and peak RAM in bytes.

    The peak is that of this child alone. `RUSAGE_CHILDREN` would give the largest child of the
    whole session, so a small book would inherit the peak of a big one. POSIX takes it from the
    rusage that `os.wait4` returns for the child. Windows reads PeakWorkingSetSize from the handle
    that `Popen` keeps open after the exit. The child is killed after `timeout` seconds.
    """
    env = None
    if sys.platform == "win32" and cmd[0] == sys.executable != sys._base_executable:
        # The python.exe of a venv only starts the base interpreter and waits for it, so its own
        # peak is a few MB and a kill would miss the interpreter. Start the interpreter itself,
        # the way multiprocessing does (bpo-35797).
        cmd = [sys._base_executable, *cmd[1:]]
        env = {**os.environ, "__PYVENV_LAUNCHER__": sys.executable}
    start = time.monotonic()
    with log.open("wb") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        try:
            if sys.platform == "win32":
                proc.wait()
                peak = _peak_working_set(proc._handle)
            else:
                _, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
                peak = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)  # bytes, KiB
        finally:
            killer.cancel()
    return proc.returncode, time.monotonic() - start, peak


def time_verdict(seconds: float, limit: float, system: str, machine: str) -> str:
    """'pass' within `limit`. Over it, 'fail' on macOS arm64 and 'skip' anywhere else: the limit of
    AC2 is defined for an M3 Mac, so the time of another machine is not comparable."""
    if seconds <= limit:
        return "pass"
    return "fail" if (system, machine) == ("Darwin", "arm64") else "skip"


class _MemoryStatus(ctypes.Structure):
    """MEMORYSTATUSEX of sysinfoapi.h."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _sysctl(name: str) -> str:
    return subprocess.run(
        ["sysctl", "-n", name], capture_output=True, text=True, check=True
    ).stdout.strip()


def hardware() -> str:
    """The CPU name and the RAM of this machine, which the time of a conversion depends on."""
    cpu, ram = platform.processor() or platform.machine(), 0
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
                ram = status.ullTotalPhys
        elif sys.platform == "darwin":
            cpu, ram = _sysctl("machdep.cpu.brand_string"), int(_sysctl("hw.memsize"))
        else:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace")
            if found := re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.MULTILINE):
                cpu = found.group(1).strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # the name and the RAM are for the log: a machine that hides them still runs the test
    return f"{cpu}, {ram / 2**30:.1f} GiB RAM" if ram else f"{cpu}, RAM unknown"


def epubcheck_tools() -> tuple[str, str]:
    """The `java` and the `epubcheck.jar` that ECO_JAVA and ECO_EPUBCHECK_JAR name. Skips the test
    when either is not set, so a machine without them still runs the rest."""
    java, jar = os.environ.get("ECO_JAVA"), os.environ.get("ECO_EPUBCHECK_JAR")
    if not (java and jar):
        pytest.skip(
            "EPUBCheck is not set up: set ECO_JAVA and ECO_EPUBCHECK_JAR to the paths of "
            "java and epubcheck.jar"
        )
    return java, jar


def epubcheck_problems(path: Path, java: str, jar: str) -> list[str]:
    """The ERROR and FATAL lines that EPUBCheck prints for an EPUB. A non-zero exit without such a
    line is a problem too, so a crash cannot pass for a clean book."""
    run = subprocess.run(
        [java, "-jar", jar, str(path)],
        capture_output=True,
        check=False,  # the exit code is read below
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,  # only stops a hang
    )
    output = run.stdout + run.stderr
    problems = [line for line in output.splitlines() if line.startswith(("ERROR(", "FATAL("))]
    if run.returncode and not problems:
        problems.append(f"EPUBCheck exited {run.returncode}: {output.strip()[-300:]}")
    return problems


def sample(pattern: str) -> Path:
    """The first file of `samples/` that matches `pattern`. Skips the test when there is none."""
    found = sorted(SAMPLES.glob(pattern))
    if not found:
        pytest.skip(f"samples/{pattern} is missing")
    return found[0]


def ground_truth_blocks(name: str) -> list[list[str]]:
    """The code blocks of `samples/ground-truth/<name>`: runs of lines between blank lines, each
    line with its white space made into one space, as `code_blocks` does for the output. The book
    text stays in the owner's local folder, never in this public repo."""
    text = sample(f"ground-truth/{name}").read_text(encoding="utf-8")
    return [
        [" ".join(line.split()) for line in block.split("\n")]
        for block in re.split(r"\n\s*\n", text.strip())
    ]
