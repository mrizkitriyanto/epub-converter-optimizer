"""The bundled EPUBCheck gate, without depending on a system Java installation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from eco.epub.validator import EpubValidationError, validate_epub


def _tools(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    java = tmp_path / ("java.exe" if os.name == "nt" else "java")
    jar = tmp_path / "epubcheck.jar"
    java.touch()
    jar.touch()
    monkeypatch.setenv("ECO_JAVA", str(java))
    monkeypatch.setenv("ECO_EPUBCHECK_JAR", str(jar))
    return java, jar


def test_source_install_without_tools_keeps_converting(monkeypatch, tmp_path):
    monkeypatch.delenv("ECO_JAVA", raising=False)
    monkeypatch.delenv("ECO_EPUBCHECK_JAR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Java was called"))
    assert validate_epub(tmp_path / "book.epub") == []


def test_partial_tool_configuration_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("ECO_JAVA", "java")
    monkeypatch.delenv("ECO_EPUBCHECK_JAR", raising=False)
    with pytest.raises(EpubValidationError, match="ECO_JAVA.*ECO_EPUBCHECK_JAR"):
        validate_epub(tmp_path / "book.epub")


def test_bundled_tools_are_used_without_host_java(monkeypatch, tmp_path):
    monkeypatch.delenv("ECO_JAVA", raising=False)
    monkeypatch.delenv("ECO_EPUBCHECK_JAR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "eco.exe"))
    java = tmp_path / "runtime" / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")
    jar = tmp_path / "runtime" / "epubcheck" / "epubcheck.jar"
    java.parent.mkdir(parents=True)
    jar.parent.mkdir(parents=True)
    java.touch()
    jar.touch()

    def run(cmd, **kwargs):
        assert cmd == [str(java), "-jar", str(jar), str(tmp_path / "book.epub")]
        return subprocess.CompletedProcess(cmd, 0, "No errors or warnings detected.\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert validate_epub(tmp_path / "book.epub") == []


def test_missing_bundled_tools_fail(monkeypatch, tmp_path):
    monkeypatch.delenv("ECO_JAVA", raising=False)
    monkeypatch.delenv("ECO_EPUBCHECK_JAR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "eco.exe"))
    with pytest.raises(EpubValidationError, match="bundled EPUBCheck"):
        validate_epub(tmp_path / "book.epub")


def test_warning_does_not_fail_validation(monkeypatch, tmp_path):
    _tools(tmp_path, monkeypatch)
    line = "WARNING(OPF-003): book.epub/OEBPS/chapter.xhtml: redundant metadata"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, line + "\n", ""),
    )
    assert validate_epub(tmp_path / "book.epub") == [line]


def test_epubcheck_error_fails_validation(monkeypatch, tmp_path):
    _tools(tmp_path, monkeypatch)
    line = "ERROR(RSC-005): book.epub/OEBPS/chapter.xhtml: invalid markup"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, line + "\n", ""),
    )
    with pytest.raises(EpubValidationError, match="RSC-005"):
        validate_epub(tmp_path / "book.epub")


def test_nonzero_exit_without_error_line_still_fails(monkeypatch, tmp_path):
    _tools(tmp_path, monkeypatch)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 2, "", "Java heap space"),
    )
    with pytest.raises(EpubValidationError, match="Java heap space"):
        validate_epub(tmp_path / "book.epub")
