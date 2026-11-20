"""Build a portable eco archive with EPUBCheck and its private Java runtime."""

import argparse
import hashlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
JRE_RELEASE = "jdk-21.0.13%2B9"
EPUBCHECK_URL = "https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip"
EPUBCHECK_SHA256 = "33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c"


@dataclass(frozen=True)
class Target:
    name: str
    os: str
    arch: str
    extension: str
    jre_sha256: str

    @property
    def jre_url(self) -> str:
        return (
            f"https://github.com/adoptium/temurin21-binaries/releases/download/{JRE_RELEASE}/"
            f"OpenJDK21U-jre_{self.arch}_{self.os}_hotspot_21.0.13_9.{self.extension}"
        )


TARGETS = {
    ("win32", "amd64"): Target(
        "windows-x64",
        "windows",
        "x64",
        "zip",
        "2332c0b4cff6bed722da3567c91d5e47568bcba863fa4945d0a8d6fc76158628",
    ),
    ("darwin", "arm64"): Target(
        "macos-arm64",
        "mac",
        "aarch64",
        "tar.gz",
        "225bab0a09491ef06835488cd942f5d2befa9a0410a2484f0c8bbcf7506ec09a",
    ),
    ("linux", "x86_64"): Target(
        "linux-x64",
        "linux",
        "x64",
        "tar.gz",
        "a535a1df9c6284d9618872984e026ae0352d1f7e9e0605425c0e6114f47351dd",
    ),
}


def target_for(system: str, machine: str) -> Target:
    key = (system, machine.lower())
    if key == ("win32", "x86_64"):
        key = ("win32", "amd64")
    try:
        return TARGETS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported native target: {system}/{machine}") from exc


def verify_sha256(path: Path, expected: str) -> None:
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")


def _download(url: str, path: Path, sha256: str) -> Path:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as output:
            shutil.copyfileobj(response, output)
    verify_sha256(path, sha256)
    return path


def _safe_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not (path.is_absolute() or ".." in path.parts or ":" in path.parts[0])


def _extract(archive: Path, dest: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as source:
            if any(not _safe_name(name) for name in source.namelist()):
                raise ValueError("unsafe archive path")
            source.extractall(dest)
    else:
        with tarfile.open(archive, "r:gz") as source:
            if any(not _safe_name(member.name) for member in source.getmembers()):
                raise ValueError("unsafe archive path")
            source.extractall(dest, filter="data")


def install_runtime(jre_archive: Path, epubcheck_archive: Path, app: Path, target: Target) -> None:
    """Copy verified archive contents into the layout that the validator discovers."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        jre, epubcheck = scratch / "jre", scratch / "epubcheck"
        _extract(jre_archive, jre)
        _extract(epubcheck_archive, epubcheck)
        java_name = "java.exe" if target.os == "windows" else "java"
        java = next((p for p in jre.rglob(java_name) if p.parent.name == "bin"), None)
        jar = next(epubcheck.rglob("epubcheck.jar"), None)
        if java is None or jar is None or not (jar.parent / "lib").is_dir():
            raise ValueError("The downloaded JRE or EPUBCheck archive is incomplete")
        runtime = app / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        shutil.copytree(java.parent.parent, runtime / "jre", dirs_exist_ok=True)
        shutil.copytree(jar.parent, runtime / "epubcheck", dirs_exist_ok=True)


def build(target: Target, jre_archive: Path | None, epubcheck_archive: Path | None) -> Path:
    out = ROOT / "out" / "native"
    cache = out / "downloads"
    jre_archive = jre_archive or _download(
        target.jre_url, cache / f"temurin21-jre.{target.extension}", target.jre_sha256
    )
    epubcheck_archive = epubcheck_archive or _download(
        EPUBCHECK_URL, cache / "epubcheck-5.4.0.zip", EPUBCHECK_SHA256
    )
    verify_sha256(jre_archive, target.jre_sha256)
    verify_sha256(epubcheck_archive, EPUBCHECK_SHA256)
    vision = importlib.util.find_spec("torchvision")
    if vision is None or vision.submodule_search_locations is None:
        raise RuntimeError("torchvision is required to build the native app")
    vision_dir = Path(next(iter(vision.submodule_search_locations)))
    # PyInstaller's dynamic-library glob misses _C_stable.so and Windows .pyd files.
    vision_binaries = sorted(vision_dir.glob("*_stable.*"))
    if not any(path.name.startswith("_C_stable.") for path in vision_binaries):
        raise RuntimeError("torchvision native operations are missing")
    binary_args = [
        arg
        for path in vision_binaries
        for arg in ("--add-binary", f"{path}{os.pathsep}torchvision")
    ]
    dist = out / "dist"
    work = out / "work"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--name",
            "eco",
            "--collect-all",
            "eco",
            "--collect-data",
            "latex2mathml",
            "--collect-data",
            "docling_parse",
            "--copy-metadata",
            "docling-slim",
            "--hidden-import",
            "docling.models.plugins.defaults",
            "--collect-binaries",
            "torchvision",
            *binary_args,
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            str(ROOT / "src" / "eco" / "__main__.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    app = dist / "eco"
    install_runtime(jre_archive, epubcheck_archive, app, target)
    java = app / "runtime" / "jre" / "bin" / ("java.exe" if target.os == "windows" else "java")
    jar = app / "runtime" / "epubcheck" / "epubcheck.jar"
    subprocess.run([str(java), "-jar", str(jar), "--version"], check=True)
    version = (ROOT / "src" / "eco" / "__init__.py").read_text(encoding="utf-8")
    version = version.split('__version__ = "', 1)[1].split('"', 1)[0]
    base = out / f"eco-{version}-{target.name}"
    archive_type = "zip" if target.os == "windows" else "gztar"
    return Path(shutil.make_archive(str(base), archive_type, root_dir=dist, base_dir="eco"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jre-archive", type=Path)
    parser.add_argument("--epubcheck-archive", type=Path)
    args = parser.parse_args()
    target = target_for(sys.platform, platform.machine())
    print(build(target, args.jre_archive, args.epubcheck_archive))


if __name__ == "__main__":
    main()
