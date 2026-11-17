import argparse

from eco import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eco", description="Convert PDF and Markdown to EPUB.")
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"eco {__version__}")
        return 0
    parser.print_help()
    return 0
