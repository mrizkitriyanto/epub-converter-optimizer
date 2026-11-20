# Native EPUBCheck Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship native eco archives for Windows x64, macOS arm64, and Linux x64 that validate every produced EPUB with bundled EPUBCheck and Java.

**Architecture:** A small validator module finds the bundled tools (or explicit developer paths) and runs EPUBCheck. The pipeline validates a temporary EPUB before moving it to its published path. A platform build script creates a PyInstaller one-folder app and adds verified upstream JRE and EPUBCheck archives; CI builds and smokes each platform.

**Tech Stack:** Python 3.12, PyInstaller, Temurin JRE 21, EPUBCheck 5.4.0, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-20-native-epubcheck-design.md`

## Global Constraints

- Native archives target Windows x64, macOS arm64, and Linux x64; no host Java or Python.
- No third-party binaries or sample books in Git. Preserve bundled upstream notices and `epubcheck/lib/`.
- Conversion itself never downloads anything. EPUBCheck errors fail a file; warnings do not.
- Source `uv` installs remain usable without validation tools; native archives always validate.
- No new UI design. Keep CLI and web messages in English.

## Review Focus

- Bundled Java or JAR missing: native conversion fails clearly without publishing an EPUB.
- EPUBCheck exits nonzero without an `ERROR` line: conversion still fails.
- EPUBCheck emits warnings only: output remains available and warnings reach the user.
- Output directory differs from the system temporary drive: final move remains on the same filesystem.
- A batch has one invalid EPUB: other files still finish.

---

### Task 1: Validator

**Files:** Create `src/eco/epub/validator.py`; test `tests/epub/test_validator.py`.

**Interfaces:** `validate_epub(path: Path) -> list[str]` returns warning lines, raises `EpubValidationError` on errors or unavailable bundled tools, and skips only when neither environment variable is set in a source install. `ECO_JAVA` and `ECO_EPUBCHECK_JAR` override bundled discovery. The native layout is `<executable>/runtime/jre/bin/java[.exe]` plus `<executable>/runtime/epubcheck/epubcheck.jar`.

- [ ] Write tests for source skip, partial configuration, frozen bundle discovery, warnings, explicit errors, nonzero exit without errors, and missing bundled files.
- [ ] Run the tests and confirm they fail because the validator does not exist.
- [ ] Implement discovery, subprocess call, bounded diagnostics, and warning extraction; keep only `ERROR(`, `FATAL(` and `WARNING(` lines.
- [ ] Run validator tests and Ruff; commit.

### Task 2: Publish only validated EPUBs

**Files:** Modify `src/eco/pipeline.py`; test `tests/test_pipeline.py` or the existing pipeline test module.

**Interfaces:** Call `validate_epub` after `optimize_epub` and before `Path.replace(out)`. Convert to a temporary path inside `out_dir`; add warning findings with kind `epubcheck_warning` and page 0.

- [ ] Write tests showing invalid output is absent, a valid output is published, and warnings are reported; exercise CLI/web batch behavior where practical.
- [ ] Run targeted tests and confirm expected failures.
- [ ] Implement temporary output, validation, and publication. Validation failure for a mixed EPUB/XTC request stops that file before XTC writing.
- [ ] Run targeted tests and Ruff; commit.

### Task 3: Native archive builder

**Files:** Create `scripts/build-native.py`; test `tests/test_native_build.py`; update `.gitignore` for build outputs.

**Interfaces:** `python scripts/build-native.py` runs on the current target OS, downloads pinned Temurin JRE and EPUBCheck assets with SHA-256 verification, invokes PyInstaller in one-folder mode, normalizes JRE layout, preserves upstream notices, and writes one portable archive under `out/native/`. The installed `eco` command should discover `<executable>/runtime/`.

- [ ] Write tests for platform selection, archive extraction/path safety, checksum mismatch, and assembled runtime layout using local fixture archives.
- [ ] Run tests and confirm expected failures.
- [ ] Implement the builder with standard library code and a pinned PyInstaller build dependency; keep downloads build-time only.
- [ ] Build the Windows archive; run `eco --help`, `eco web` health, and a Markdown-to-EPUB conversion through bundled EPUBCheck. Commit.

### Task 4: CI and install docs

**Files:** Modify `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `README.md`, `README.id.md`, `docs/install-check.md`, and `docs/decisions.md`.

**Interfaces:** CI checks one native archive per OS on pull requests, including a bundled validator smoke conversion. Tagged releases upload the three archives. Docs name the archives and explain unpacking, `eco setup`, and the source-install validator override.

- [ ] Add a CI smoke check that fails if the runtime is absent or a generated EPUB is invalid.
- [ ] Add three platform build jobs and release uploads, then update installation docs and decision log.
- [ ] Run the fast suite, Ruff check/format, and the Windows native smoke again; commit.

## Final verification

- [ ] Review the whole branch against the spec, run the full fast suite, inspect the package archive and licenses, and report any CI-only platform limits before integration.
