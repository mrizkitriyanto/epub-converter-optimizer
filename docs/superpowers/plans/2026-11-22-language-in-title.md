# Language in Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every converted EPUB and XTC title reads `<CODE> - <title>`, `dc:language` is corrected when the text decides it, and EPUB 3 `dcterms:modified` is the conversion time.

**Architecture:** `eco.naming` splits out `language_code()` and `titled()`; `convert_file` builds the book facts once before the optimizer, passes the code and detected language to `optimize_epub` (which edits the OPF it already holds) and to `_write_xtc`; `library_name` drops a same-code prefix so names never double.

**Tech Stack:** Python stdlib (xml.etree, datetime).

**Spec:** `docs/superpowers/specs/2026-11-22-language-in-title-design.md`

## Global Constraints

- English in code, comments, docs. No new dependency. No network during conversion.
- Naming and title work never fail a conversion: any error gives no code and the book converts as before.
- No toggle, no CLI flag. Every device.
- Only the first `dc:title` and the first `dc:language` of the OPF change; NCX, nav and pages keep their text.

## Review Focus

- An eco output converted again (`ID - Deep Work` with Indonesian text): stays `ID - Deep Work`, download name `ID - Deep Work - ...`.
- An EPUB with no `dc:language` and Indonesian text: gains `<dc:language>id</dc:language>`.
- Metadata `ja-JP` and text that is neither English nor Indonesian: title `JA - ...`, `dc:language` stays `ja-JP`.
- An EPUB 2 package: title and language change, no `dcterms:modified` is added.
- An unreadable OPF for naming: the book converts with its title untouched.

---

### Task 1: `language_code`, `titled`, no doubled prefix

**Files:** Modify `src/eco/naming.py`; Test `tests/test_naming.py`

**Interfaces — Produces:**
- `language_code(facts: BookFacts) -> tuple[str, str | None]`: (`"ID"`/`"EN"`/metadata primary subtag upper / `""`, `"id"`/`"en"` when the text decided else `None`).
- `titled(title: str, code: str) -> str`: `f"{code} - {title}"`; unchanged when `code` is `""` or the title already starts with `f"{code} - "`.
- `library_name` uses `language_code` and strips a leading `f"{code} - "` from the title first.

- [ ] **Step 1: Failing tests**

```python
from eco.naming import language_code, titled

def test_language_code_says_where_it_came_from():
    assert language_code(facts("T")) == ("ID", "id")
    assert language_code(facts("T", text=EN_TEXT)) == ("EN", "en")
    assert language_code(facts("T", language="ja-JP", text="猫")) == ("JA", None)
    assert language_code(facts("T", text="猫")) == ("", None)

def test_titled_adds_the_code_once():
    assert titled("Deep Work", "ID") == "ID - Deep Work"
    assert titled("ID - Deep Work", "ID") == "ID - Deep Work"
    assert titled("Deep Work", "") == "Deep Work"

def test_a_prefixed_title_does_not_double_in_the_name():
    assert library_name(facts("ID - Deep Work", ["Cal Newport"])) == "ID - Deep Work - Cal Newport"
```

- [ ] **Step 2:** `uv run pytest tests/test_naming.py -q` — Expected: ImportError / FAIL.
- [ ] **Step 3:** Implement; `library_name` takes its code from `language_code`.
- [ ] **Step 4:** `uv run pytest tests/test_naming.py -q` — Expected: PASS; `uv run ruff check`.
- [ ] **Step 5:** Commit `feat(naming): language code and titled() for book titles`.

---

### Task 2: the optimizer writes title, language and modified

**Files:** Modify `src/eco/epub/optimizer.py` (`optimize_epub`, `_Package.__init__`, a `_label()` step in `run()`); Test `tests/epub/test_optimizer.py`

**Interfaces — Produces:** `optimize_epub(src, dst, options, code: str = "", language: str | None = None) -> OptimizeReport`; `_Package(src, options, code="", language=None)`.

- [ ] **Step 1: Failing tests** (build EPUBs with `fixtures.make.book_epub`; read the OPF back with zipfile + ElementTree):
  - `test_the_title_gets_the_code_and_the_language_is_fixed`: `book_epub(..., "Deep Work", ["Cal Newport"], "en", [...])`, `optimize_epub(src, dst, Options(), code="ID", language="id")` → first `dc:title` `"ID - Deep Work"`, first `dc:language` `"id"`.
  - `test_no_code_leaves_the_title`: `code=""` → title unchanged, language unchanged.
  - `test_a_missing_language_is_added`: `book_epub(..., language="")` with `language="id"` → one `dc:language` `"id"`.
  - `test_metadata_only_code_keeps_the_language`: `code="JA", language=None` on `ja-JP` → title `"JA - ..."`, language `"ja-JP"`.
  - `test_modified_is_the_conversion_time_on_epub3`: the `meta[@property='dcterms:modified']` text matches `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$` and is not the fixture's value; on an EPUB 2 package (version `"2.0"`) none is added.
  - `test_the_prefix_is_not_doubled`: title `"ID - Deep Work"`, `code="ID"` → `"ID - Deep Work"`.
- [ ] **Step 2:** `uv run pytest tests/epub/test_optimizer.py -q -k "title or language or modified or prefix"` — Expected: FAIL (unexpected keyword).
- [ ] **Step 3:** Implement `_label()` in `run()` before `_tidy()`: edit `self.opf.root`'s metadata with the DC namespace `http://purl.org/dc/elements/1.1/` (`titled` from Task 1); `dcterms:modified` only when `version` starts with `3`, value `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`, updating the existing element or adding one. Make sure the OPF is written back (the same way other OPF edits are).
- [ ] **Step 4:** `uv run pytest tests/epub -q` — Expected: PASS.
- [ ] **Step 5:** Commit `feat(epub): language code in the title, language fixed, modified time`.

---

### Task 3: the pipeline passes it on; XTC title; docs

**Files:** Modify `src/eco/pipeline.py`, `README.md`, `README.id.md`, `docs/decisions.md`; Test `tests/test_pipeline.py`

**Interfaces — Consumes:** Task 1 and Task 2. `_library_name` is replaced by `_facts(path, kind, source, options) -> BookFacts | None` (same rules, never raises), called once before the optimizer; `Result.library_name` = `library_name(facts)`.

- [ ] **Step 1: Failing tests:**
  - `test_the_epub_title_carries_the_language`: Markdown with `title: "Buku Saya"`, Indonesian body → output OPF `dc:title` `"ID - Buku Saya"`, `dc:language` `"id"`; `result.library_name == "ID - Buku Saya - Ani"`.
  - `test_an_english_labelled_indonesian_epub_is_fixed`: `book_epub(..., "Deep Work", ["Cal Newport"], "en", [ID body])` → `dc:title` `"ID - Deep Work"`, `dc:language` `"id"`.
  - `test_the_xtc_title_carries_the_language`: Markdown → `formats=("xtch",)`, `read_container(out.read_bytes())[0]["title"] == "ID - Buku Saya"` (device `x4-pro`).
  - `test_naming_trouble_leaves_the_title`: monkeypatch `pipeline.facts_from_epub` to raise → the EPUB converts, `dc:title` unchanged.
- [ ] **Step 2:** `uv run pytest tests/test_pipeline.py -q -k "title or naming_trouble"` — Expected: FAIL.
- [ ] **Step 3:** Implement: `facts = _facts(...)` right after the source is ready; `code, language = language_code(facts) if facts else ("", None)`; pass to `optimize_epub(built, staged, options, code, language)`; in `_write_xtc` the container title is `titled(title, code)` and the language `language or source.meta.get("language", "")` (pass `code` and `language` in). Docs: README Export/EPUB sentence (both languages), dated `docs/decisions.md` entry.
- [ ] **Step 4:** `uv run pytest tests -q --deselect tests/web/test_jobs.py::test_list_is_newest_first`, `uv run ruff check`, `uv run ruff format --check` — Expected: all PASS.
- [ ] **Step 5:** Commit `feat: language code in EPUB and XTC titles`.
