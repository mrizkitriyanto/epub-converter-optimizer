"""Run the EPUB conformance check included with native eco packages."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


class EpubValidationError(ValueError):
    """The generated EPUB failed validation or its validator could not run."""


def _tools() -> tuple[str, str] | None:
    java, jar = os.environ.get("ECO_JAVA"), os.environ.get("ECO_EPUBCHECK_JAR")
    if bool(java) != bool(jar):
        raise EpubValidationError("Set both ECO_JAVA and ECO_EPUBCHECK_JAR, or neither.")
    if java and jar:
        if not (Path(java).is_file() or shutil.which(java)) or not Path(jar).is_file():
            raise EpubValidationError("ECO_JAVA or ECO_EPUBCHECK_JAR does not exist.")
        return java, jar
    if not getattr(sys, "frozen", False):
        return None
    runtime = Path(sys.executable).parent / "runtime"
    java_path = runtime / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")
    jar_path = runtime / "epubcheck" / "epubcheck.jar"
    if not java_path.is_file() or not jar_path.is_file():
        raise EpubValidationError("The bundled EPUBCheck runtime is missing or incomplete.")
    return str(java_path), str(jar_path)


def validate_epub(path: Path) -> list[str] | None:
    """Return EPUBCheck warnings, or raise before an invalid EPUB is published. None when no
    EPUBCheck is configured (a source install): nothing ran."""
    tools = _tools()
    if tools is None:
        return None
    java, jar = tools
    try:
        result = subprocess.run(
            [java, "-jar", jar, str(path)],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EpubValidationError(f"EPUBCheck could not run: {exc}") from exc
    output = result.stdout + result.stderr
    problems = [line for line in output.splitlines() if line.startswith(("ERROR(", "FATAL("))]
    if problems:
        raise EpubValidationError("EPUBCheck found errors: " + " | ".join(problems[:5])[:1000])
    if result.returncode:
        raise EpubValidationError(f"EPUBCheck exited {result.returncode}: {output.strip()[-300:]}")
    return [line for line in output.splitlines() if line.startswith("WARNING(")]
