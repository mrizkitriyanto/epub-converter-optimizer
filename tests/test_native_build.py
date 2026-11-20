"""Native archive assembly can run without network or PyInstaller in these tests."""

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.build_native import install_runtime, target_for, verify_sha256


def test_supported_build_targets_are_platform_specific():
    assert target_for("win32", "AMD64").name == "windows-x64"
    assert target_for("darwin", "arm64").name == "macos-arm64"
    assert target_for("linux", "x86_64").name == "linux-x64"
    assert target_for("linux", "x86_64").jre_url.endswith(
        "/OpenJDK21U-jre_x64_linux_hotspot_21.0.13_9.tar.gz"
    )
    with pytest.raises(ValueError, match="Unsupported native target"):
        target_for("darwin", "x86_64")


def test_checksum_mismatch_stops_assembly(tmp_path):
    archive = tmp_path / "download.zip"
    archive.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_sha256(archive, "0" * 64)
    verify_sha256(archive, hashlib.sha256(b"corrupted").hexdigest())


def _epubcheck_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name in (
            "epubcheck-5.4.0/epubcheck.jar",
            "epubcheck-5.4.0/lib/dependency.jar",
            "epubcheck-5.4.0/LICENSE.txt",
            "epubcheck-5.4.0/THIRD-PARTY.txt",
        ):
            z.writestr(name, b"fixture")


def test_windows_bundle_has_java_jar_lib_and_licenses(tmp_path):
    jre = tmp_path / "jre.zip"
    check = tmp_path / "check.zip"
    with zipfile.ZipFile(jre, "w") as z:
        z.writestr("jdk-21-jre/bin/java.exe", b"java")
        z.writestr("jdk-21-jre/NOTICE", b"notice")
        z.writestr("jdk-21-jre/legal/java.base/LICENSE", b"license")
    _epubcheck_zip(check)
    app = tmp_path / "app"

    install_runtime(jre, check, app, target_for("win32", "AMD64"))

    assert (app / "runtime/jre/bin/java.exe").read_bytes() == b"java"
    assert (app / "runtime/jre/legal/java.base/LICENSE").exists()
    assert (app / "runtime/epubcheck/epubcheck.jar").exists()
    assert (app / "runtime/epubcheck/lib/dependency.jar").exists()
    assert (app / "runtime/epubcheck/LICENSE.txt").exists()


def test_mac_jre_contents_home_is_normalized(tmp_path):
    jre = tmp_path / "jre.tar.gz"
    check = tmp_path / "check.zip"
    with tarfile.open(jre, "w:gz") as tar:
        for name, data in (
            ("jdk-21-jre/Contents/Home/bin/java", b"java"),
            ("jdk-21-jre/Contents/Home/NOTICE", b"notice"),
        ):
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o755
            tar.addfile(item, io.BytesIO(data))
    _epubcheck_zip(check)
    app = tmp_path / "app"

    install_runtime(jre, check, app, target_for("darwin", "arm64"))

    assert (app / "runtime/jre/bin/java").read_bytes() == b"java"
    assert (app / "runtime/jre/NOTICE").exists()


def test_zip_path_traversal_is_rejected(tmp_path):
    jre = tmp_path / "jre.zip"
    check = tmp_path / "check.zip"
    with zipfile.ZipFile(jre, "w") as z:
        z.writestr("../outside", b"unsafe")
    _epubcheck_zip(check)
    with pytest.raises(ValueError, match="unsafe archive path"):
        install_runtime(jre, check, tmp_path / "app", target_for("win32", "AMD64"))
    assert not (tmp_path / "outside").exists()
