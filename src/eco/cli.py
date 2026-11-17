import argparse
import sys

from eco import __version__, models
from eco.options import resolve_data_dir


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
    try:
        models.download_models(d, ipv4=args.ipv4)
    except RuntimeError as e:
        print(f"eco setup: {e}", file=sys.stderr)
        return 1
    print(f"Models ready in {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eco", description="Convert PDF and Markdown to EPUB.")
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("setup", help="download the AI models (asks first)")
    setup.add_argument("--yes", action="store_true", help="download without asking")
    setup.add_argument("--ipv4", action="store_true", help="connect over IPv4 only")
    setup.add_argument(
        "--data", metavar="DIR", help="data folder (default: ECO_DATA or the app folder)"
    )
    args = parser.parse_args(argv)
    if args.version:
        print(f"eco {__version__}")
        return 0
    if args.command == "setup":
        return _setup(args)
    parser.print_help()
    return 0
