import zipfile
from pathlib import Path

_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}


def write_epub_zip(dst: Path, files: dict[str, bytes]) -> None:
    """Write an EPUB container: `mimetype` first and stored, the rest deflated, OS junk skipped."""
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name in sorted(files):
            parts = name.split("/")
            if name == "mimetype" or "__MACOSX" in parts or parts[-1].lower() in _JUNK_FILES:
                continue
            z.writestr(name, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
