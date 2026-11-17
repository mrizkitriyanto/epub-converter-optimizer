import zipfile
from pathlib import Path

_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
MAX_EPUB_BYTES = 2**30


def check_expansion(z: zipfile.ZipFile, name: str) -> None:
    """Refuse an archive that unpacks to more than 1 GiB. The zip directory states every size, so
    this runs before any entry is read."""
    if sum(info.file_size for info in z.infolist()) > MAX_EPUB_BYTES:
        raise ValueError(f"EPUB expands to more than 1 GiB: {name}")


def write_epub_zip(dst: Path, files: dict[str, bytes]) -> None:
    """Write an EPUB container: `mimetype` first and stored, the rest deflated, OS junk skipped."""
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name in sorted(files):
            parts = name.split("/")
            if name == "mimetype" or "__MACOSX" in parts or parts[-1].lower() in _JUNK_FILES:
                continue
            z.writestr(name, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
