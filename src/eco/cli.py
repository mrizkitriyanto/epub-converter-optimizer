import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from eco import __version__, models
from eco.events import Finding, FindingEvent, PageEvent, StageEvent
from eco.options import (
    DEVICES,
    FIRMWARES,
    FORMATS,
    MODES,
    OCR_MODES,
    SIZES,
    Options,
    resolve_data_dir,
)

_INPUT_SUFFIXES = (".pdf", ".md", ".epub")
_OUTPUT_SUFFIXES = tuple(f".{device}.epub" for device in DEVICES)


def _error(e: Exception) -> None:
    print(f"error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)


def _progress(event) -> None:
    if isinstance(event, StageEvent) and event.status == "started":
        print(f"[{event.stage}]", file=sys.stderr)
    elif isinstance(event, PageEvent):
        print(f"[layout] page {event.done}/{event.total}", file=sys.stderr)


def _human(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    return f"{size / 1000:.0f} KB" if size < 1_000_000 else f"{size / 1_000_000:.1f} MB"


def _size(path: Path) -> int:
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return path.stat().st_size


def _print_findings(findings: list[Finding]) -> None:
    counts = Counter(f.kind for f in findings)
    print("  findings: " + (", ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "none"))
    for f in findings:
        if f.level == "warning":
            print(f"  warning: page {f.page}: {f.message}")


def _expand(inputs: list[str]) -> tuple[list[Path], int]:
    """The files to convert, and how many folders gave none. A folder stands for the files and
    `.book` folders in it, except `<stem>.<device>.epub`, the output of an earlier run. A `.book`
    folder, or a file named on the command line, is itself an input."""
    files, failed = [], 0
    for name in inputs:
        path = Path(name).expanduser()
        if path.is_dir() and path.suffix != ".book":
            found = sorted(
                p
                for p in path.iterdir()
                if (
                    p.is_file()
                    and p.suffix.lower() in _INPUT_SUFFIXES
                    and not p.name.lower().endswith(_OUTPUT_SUFFIXES)
                )
                or (p.is_dir() and p.suffix == ".book")
            )
            if not found:
                _error(FileNotFoundError(f"No PDF, Markdown or EPUB files in {path}"))
                failed += 1
            files += found
        else:
            files.append(path)
    return files, failed


def _convert(args: argparse.Namespace) -> int:
    from eco.pipeline import convert_file  # imported late: it loads Docling

    data = resolve_data_dir(args.data)
    options = Options(
        device=args.device,
        firmware=args.firmware,
        formats=(args.format,),
        size=args.size,
        mode=args.mode,
        landscape=args.landscape,
        ocr=args.ocr,
        title=args.title,
        author=args.author,
        lang=args.lang,
    )
    files, failed = _expand(args.inputs)
    written: list[Path] = []
    for path in files:
        try:
            if not path.exists():
                raise FileNotFoundError(f"No such file or folder: {path}")
            result = convert_file(
                path,
                options,
                Path(args.output).expanduser() if args.output else path.parent,
                data_dir=data,
                on_event=_progress,
                inputs=(*files, *written),
            )
        except Exception as e:  # noqa: BLE001  one bad file must not stop the batch
            _error(e)
            failed += 1
            continue
        out = result.outputs["epub"]
        written.append(out)
        print(out)
        print(f"  size: {_human(_size(path))} -> {_human(result.sizes['epub'])}")
        _print_findings(result.findings)
    return 1 if failed else 0


def _extract(args: argparse.Namespace) -> int:
    from eco.pdf.pages import pdf_metadata
    from eco.pipeline import extract_pdf

    pdf = Path(args.input).expanduser()
    findings: list[Finding] = []

    def on_event(event) -> None:
        _progress(event)
        if isinstance(event, FindingEvent):
            findings.append(event.finding)

    folder = extract_pdf(
        pdf,
        Options(ocr=args.ocr),
        data_dir=resolve_data_dir(args.data),
        on_event=on_event,
        cancel=lambda: False,
    )
    out_dir = Path(args.output).expanduser() if args.output else pdf.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    while (dest := out_dir / f"{pdf.stem}{f'-{n}' if n else ''}.book").exists():
        n += 1
    shutil.copytree(folder, dest)
    if "title" not in pdf_metadata(pdf):
        # the cache holds the file name its first extraction saw; this file may be named otherwise
        md = dest / "book.md"
        title = f"title: {json.dumps(pdf.stem, ensure_ascii=False)}"
        text = re.sub(
            r"^title: .*$", lambda _: title, md.read_text(encoding="utf-8"), 1, re.MULTILINE
        )
        md.write_text(text, encoding="utf-8")
    print(dest)
    _print_findings(findings)
    return 0


def _setup(args: argparse.Namespace) -> int:
    d = models.models_dir(resolve_data_dir(args.data))
    if models.models_ready(d):
        print(f"Models ready in {d}")
        return 0
    print(f"eco setup downloads these AI models into {d}:")
    for m in models.MODELS:
        print(f"  {m.name:<30} ~{m.size_mb} MB")
    print(f"Total download: ~{sum(m.size_mb for m in models.MODELS)} MB")
    if not args.yes:
        try:
            answer = input("Download now? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing downloaded.")
            return 1
    models.download_models(d, ipv4=args.ipv4)
    print(f"Models ready in {d}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eco", description="Convert PDF and Markdown to EPUB.")
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data", metavar="DIR", help="data folder (default: ECO_DATA or the app folder)"
    )
    commands = parser.add_subparsers(dest="command")

    setup = commands.add_parser(
        "setup", parents=[common], help="download the AI models (asks first)"
    )
    setup.add_argument("--yes", action="store_true", help="download without asking")
    setup.add_argument("--ipv4", action="store_true", help="connect over IPv4 only")

    convert = commands.add_parser("convert", parents=[common], help="convert files to EPUB")
    convert.add_argument("inputs", nargs="+", metavar="INPUT", help="PDF, Markdown, EPUB or folder")
    convert.add_argument(
        "-o", "--output", metavar="DIR", help="output folder (default: the input's folder)"
    )
    convert.add_argument("--device", choices=list(DEVICES), default="x4")
    convert.add_argument("--firmware", choices=FIRMWARES, default="any")
    convert.add_argument("--format", choices=FORMATS, default="epub")
    convert.add_argument("--size", choices=SIZES, default="balanced")
    convert.add_argument("--mode", choices=MODES, default="auto")
    convert.add_argument("--landscape", action="store_true", help="turn pages sideways (Xteink)")
    convert.add_argument("--ocr", choices=OCR_MODES, default="auto")
    convert.add_argument("--title", help="set the title")
    convert.add_argument("--author", help="set the author")
    convert.add_argument("--lang", help="set the language, for example en or id")

    extract = commands.add_parser(
        "extract", parents=[common], help="extract a PDF into an editable book folder"
    )
    extract.add_argument("input", metavar="INPUT.pdf")
    extract.add_argument("-o", "--output", metavar="DIR", help="folder for the book folder")
    extract.add_argument("--ocr", choices=OCR_MODES, default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.version:
            print(f"eco {__version__}")
            return 0
        if args.command is None:
            parser.error("a command is required: setup, convert or extract")
        if args.command == "convert" and args.landscape and args.device == "general":
            parser.error("--landscape needs an Xteink device, not --device general")
    except SystemExit as e:  # argparse exits on a usage error; main returns the code instead
        return e.code
    try:
        return {"setup": _setup, "convert": _convert, "extract": _extract}[args.command](args)
    except Exception as e:  # noqa: BLE001  every failure ends as one error line
        _error(e)
        return 1
