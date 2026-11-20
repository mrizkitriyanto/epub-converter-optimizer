import argparse
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path

import platformdirs

from eco import __version__, models
from eco.events import Finding, FindingEvent, PageEvent, StageEvent
from eco.font_library import MAX_FONT_BYTES, add_font, list_fonts, remove_font
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
from eco.saved_styles import get_default, list_styles, load_style
from eco.style import BUNDLED_FONTS, TYPST_FAMILY, PageStyle

_INPUT_SUFFIXES = (".pdf", ".md", ".epub")
_OUTPUT_SUFFIXES = tuple(f".{device}.epub" for device in DEVICES)
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
_ANY_ADDRESS = {"0.0.0.0": "127.0.0.1", "::": "[::1]"}  # and the loopback that reaches it
_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,}")
_TOKEN_RULE = "The token must be at least 16 characters, each one of A-Z, a-z, 0-9, - or _."
_BROWSER_DELAY = 1.0  # seconds: the server listens by then


def _error(e: Exception) -> None:
    print(f"error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)


def _writable_data_dir(value: str | None) -> Path:
    path = Path(
        value or os.environ.get("ECO_DATA") or platformdirs.user_data_dir("eco")
    ).expanduser()
    try:
        data = resolve_data_dir(value)
        with tempfile.TemporaryFile(dir=data):
            pass
    except OSError as e:
        raise RuntimeError(f"Data directory not writable: {path}") from e
    return data


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


def _expand(inputs: list[str]) -> tuple[list[Path], list[str]]:
    """The files to convert, and the folders that gave none. A folder stands for the files and
    `.book` folders in it, except `<stem>.<device>.epub`, the output of an earlier run. A `.book`
    folder, or a file named on the command line, is itself an input."""
    files, empty = [], []
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
                empty.append(str(path))
            files += found
        else:
            files.append(path)
    return files, empty


def _formats(value: str) -> tuple[str, ...]:
    formats = tuple(value.split(","))
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if not formats or unknown:
        allowed = ",".join(FORMATS)
        raise argparse.ArgumentTypeError(f"must be a comma list of: {allowed}")
    return formats


def _font_family(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"No such font file: {path}")
    import typst

    fonts = typst.Fonts(
        include_system_fonts=False,
        include_embedded_fonts=False,
        font_paths=[str(path.parent)],
    ).fonts()
    families = {font.family for font in fonts if Path(font.path).resolve() == path.resolve()}
    if len(families) != 1:
        raise ValueError(f"Not a usable font file: {path.name}")
    return families.pop()


def _page_style(args: argparse.Namespace, data_dir: Path) -> tuple[PageStyle, tuple[Path, ...]]:
    values = {}
    style_findings: list[Finding] = []
    if args.style:
        path = Path(args.style).expanduser()
        if path.is_file():
            values = json.loads(path.read_text(encoding="utf-8"))
        else:
            try:
                values = load_style(data_dir, args.style, findings=style_findings).to_json()
            except ValueError as error:
                if not str(error).startswith("Style not found:"):
                    raise
                names = ", ".join(item["name"] for item in list_styles(data_dir)) or "none"
                raise ValueError(f"{error}. Available styles: {names}") from None
        print(f"Style: {args.style}")
    elif default := get_default(data_dir):
        values = load_style(data_dir, default, findings=style_findings).to_json()
        print(f"Style: {default} (default)")
    library = data_dir / "fonts"
    extra_dirs = (library,) if library.is_dir() else ()
    if args.font:
        font = Path(args.font).expanduser()
        if font.suffix.lower() in (".ttf", ".otf"):
            values = {**values, "font": _font_family(font)}
            extra_dirs = (*extra_dirs, font.parent)
        else:
            families = (
                *BUNDLED_FONTS,
                TYPST_FAMILY,
                *(item["family"] for item in list_fonts(data_dir)),
            )
            if args.font not in families:
                names = ", ".join(families)
                raise ValueError(f"Unknown font: {args.font}. Available families: {names}")
            values = {**values, "font": args.font}
    if args.focus_mode or args.focus_strength is not None:
        values = {
            **values,
            **({"focus_mode": True} if args.focus_mode else {}),
            **({"focus_strength": args.focus_strength} if args.focus_strength else {}),
        }
    style = PageStyle.from_json(values, extra_dirs)
    if args.font_size is not None:
        style = PageStyle.from_json({**style.to_json(), "font_size": args.font_size}, extra_dirs)
    if style_findings:
        _print_findings(style_findings)
    return style, extra_dirs


def _convert(args: argparse.Namespace) -> int:
    from eco.pipeline import convert_file  # imported late: it loads Docling

    data = _writable_data_dir(args.data)
    style, font_extra_dirs = _page_style(args, data)
    options = Options(
        device=args.device,
        firmware=args.firmware,
        formats=args.format,
        size=args.size,
        mode=args.mode,
        landscape=args.landscape,
        ocr=args.ocr,
        title=args.title,
        author=args.author,
        lang=args.lang,
        style=style,
    )
    files, failed = _expand(args.inputs)
    written: list[Path] = []
    converted = 0
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
                font_extra_dirs=font_extra_dirs,
            )
            for fmt, out in result.outputs.items():
                written.append(out)
                print(out)
                print(f"  size: {_human(_size(path))} -> {_human(result.sizes[fmt])}")
            _print_findings(result.findings)
            converted += 1
        except Exception as e:  # noqa: BLE001  one bad file must not stop the batch
            _error(e)
            failed.append(path.name)
    if len(files) > 1 or failed:
        print(
            f"{converted} converted"
            + (f", {len(failed)} failed: {', '.join(failed)}" if failed else "")
        )
    return 1 if failed else 0


def _fonts_cli(args: argparse.Namespace) -> int:
    data = _writable_data_dir(args.data)
    if args.font_command == "list":
        for entry in list_fonts(data):
            print(f"{entry['family']}: {', '.join(map(str, entry['weights']))}")
    elif args.font_command == "add":
        for raw in args.files:
            path = Path(raw).expanduser()
            if path.stat().st_size > MAX_FONT_BYTES:
                raise ValueError(f"Not a usable font file: {path.name}")
            result = add_font(data, path.name, path.read_bytes())
            print(f"{result['family']}: {result['status']}")
    elif not remove_font(data, args.family):
        raise ValueError(f"Font not found: {args.family}")
    return 0


def _styles_cli(args: argparse.Namespace) -> int:
    for entry in list_styles(_writable_data_dir(args.data)):
        suffix = " (default)" if entry["default"] else ""
        if "error" in entry:
            suffix += f" (broken: {entry['error']})"
        print(entry["name"] + suffix)
    return 0


def _extract(args: argparse.Namespace) -> int:
    from eco.bookfolder import read_book_md
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
    markdown = read_book_md(folder, just_written=True)  # a virus scanner is named plainly
    shutil.copytree(folder, dest)
    if "title" not in pdf_metadata(pdf):
        # the cache holds the file name its first extraction saw; this file may be named otherwise
        title = f"title: {json.dumps(pdf.stem, ensure_ascii=False)}"
        text = re.sub(r"^title: .*$", lambda _: title, markdown, 1, re.MULTILINE)
        (dest / "book.md").write_text(text, encoding="utf-8")
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


def _web(args: argparse.Namespace) -> int:
    import webbrowser

    import uvicorn

    from eco.web.app import Server, create_app  # imported late: FastAPI is for this command only
    from eco.web.jobs import server_lock

    token = args.token or os.environ.get("ECO_TOKEN") or None
    if token is not None and not _TOKEN.fullmatch(token):
        print(f"error: {_TOKEN_RULE}", file=sys.stderr)
        return 2
    if token is None and args.host not in _LOOPBACK:
        token = secrets.token_urlsafe(24)
    data = _writable_data_dir(args.data)
    with server_lock(data):  # a second eco web on these jobs stops here, with one error line
        pass  # the app holds the lock while it runs
    app = create_app(data, token=token, max_upload_mb=args.max_upload_mb)
    host = f"[{args.host}]" if ":" in args.host else args.host
    query = f"?token={token}" if token else ""  # URL-safe: _TOKEN or token_urlsafe
    # no device can open the any-address; this computer's loopback reaches the server, and other
    # devices reach it at this computer's own address on the network
    local = _ANY_ADDRESS.get(args.host, host)
    print(f"Open: http://{local}:{args.port}/{query}", flush=True)
    if args.host in _ANY_ADDRESS:
        print(
            f"On another device, use this computer's network address in place of {local}.",
            flush=True,
        )
    browser = threading.Timer(
        _BROWSER_DELAY, webbrowser.open, [f"http://{local}:{args.port}/{query}"]
    )
    browser.daemon = True
    if not args.no_browser:
        browser.start()
    # `Server` ends the event streams at Ctrl+C, which uvicorn would wait for; the timeout is for
    # whatever else is in flight (an upload, a download): after 5 s uvicorn cancels it
    config = uvicorn.Config(
        app, host=args.host, port=args.port, log_level="warning", timeout_graceful_shutdown=5
    )
    try:
        Server(config).run()
    except KeyboardInterrupt:  # uvicorn raises the Ctrl+C that stopped it again, once it has
        pass
    finally:
        browser.cancel()  # the server stopped first, for example because the port is taken
    return 0


def _megabytes(value: str) -> int:
    """`--max-upload-mb`: a whole number above 0. With 0 every upload would be too large."""
    if not value.isdigit() or int(value) == 0:
        raise argparse.ArgumentTypeError("must be a whole number of MB above 0")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eco",
        description="Convert PDF and Markdown to EPUB and optimize EPUB files, on the command "
        "line or in a web browser (eco web).",
    )
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

    fonts = commands.add_parser("fonts", parents=[common], help="manage the shared font library")
    font_commands = fonts.add_subparsers(dest="font_command", required=True)
    font_commands.add_parser("list")
    font_commands.add_parser("add").add_argument("files", nargs="+", metavar="FILE")
    font_commands.add_parser("remove").add_argument("family", metavar="FAMILY")

    styles = commands.add_parser("styles", parents=[common], help="list saved reading styles")
    styles.add_subparsers(dest="style_command", required=True).add_parser("list")

    convert = commands.add_parser("convert", parents=[common], help="convert files to EPUB")
    convert.add_argument("inputs", nargs="+", metavar="INPUT", help="PDF, Markdown, EPUB or folder")
    convert.add_argument(
        "-o", "--output", metavar="DIR", help="output folder (default: the input's folder)"
    )
    convert.add_argument("--device", choices=list(DEVICES), default="x4")
    convert.add_argument("--firmware", choices=FIRMWARES, default="any")
    convert.add_argument(
        "--format",
        type=_formats,
        default=("epub",),
        metavar="LIST",
        help="comma-separated output formats: epub,xtch,xtc (default: epub)",
    )
    convert.add_argument("--size", choices=SIZES, default="balanced")
    convert.add_argument("--mode", choices=MODES, default="auto")
    convert.add_argument("--landscape", action="store_true", help="turn pages sideways (Xteink)")
    convert.add_argument("--ocr", choices=OCR_MODES, default="auto")
    convert.add_argument("--title", help="set the title")
    convert.add_argument("--author", help="set the author")
    convert.add_argument("--lang", help="set the language, for example en or id")
    convert.add_argument(
        "--style", metavar="FILE.json", help="reading style JSON or saved style name"
    )
    convert.add_argument(
        "--focus-mode", action="store_true", help="embed Focus Mode in EPUB and apply it to XTC"
    )
    convert.add_argument(
        "--focus-strength",
        choices=("low", "medium", "high"),
        help="Focus Mode strength (default: medium, or the selected style's value)",
    )
    convert.add_argument("--font", metavar="NAME|PATH", help="font family or .ttf/.otf file")
    convert.add_argument("--font-size", type=int, metavar="N", help="override the style font size")

    extract = commands.add_parser(
        "extract", parents=[common], help="extract a PDF into an editable book folder"
    )
    extract.add_argument("input", metavar="INPUT.pdf")
    extract.add_argument("-o", "--output", metavar="DIR", help="folder for the book folder")
    extract.add_argument("--ocr", choices=OCR_MODES, default="auto")

    web = commands.add_parser("web", parents=[common], help="open the converter in a web browser")
    web.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on (default: 127.0.0.1, this computer only; "
        "an address other than 127.0.0.1, localhost or ::1 needs a token)",
    )
    web.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    web.add_argument(
        "--token",
        help="access token, 16 or more of A-Z a-z 0-9 - _ (default: ECO_TOKEN; "
        "made up and printed when another address needs one)",
    )
    web.add_argument("--no-browser", action="store_true", help="do not open a browser")
    web.add_argument(
        "--max-upload-mb",
        type=_megabytes,
        default=500,
        metavar="MB",
        help="largest upload in MB (default: 500)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.version:
            print(f"eco {__version__}")
            return 0
        if args.command is None:
            parser.error("a command is required: setup, convert, extract, fonts or web")
        if args.command == "convert" and args.landscape and args.device == "general":
            parser.error("--landscape needs an Xteink device, not --device general")
    except SystemExit as e:  # argparse exits on a usage error; main returns the code instead
        return e.code
    try:
        commands = {
            "setup": _setup,
            "convert": _convert,
            "extract": _extract,
            "web": _web,
            "fonts": _fonts_cli,
            "styles": _styles_cli,
        }
        return commands[args.command](args)
    except Exception as e:  # noqa: BLE001  every failure ends as one error line
        _error(e)
        return 1
