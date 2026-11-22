# Library Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A toggle in Export downloads each file as `LANG - Title - Author` (`.epub`, or `.<device>.<xtc|xtch>`), with language, title and author found by the program at conversion time.

**Architecture:** A pure module `eco/naming.py` turns book facts (title, authors, language, text) into a name. `convert_file` builds the facts from the source it already has and puts the name on `Result`; the web worker passes it through the `done` event into `JobFile.library_name`. The download route uses it when called with `?name=library`; Export shows a remembered toggle.

**Tech Stack:** Python 3 stdlib (zipfile, xml.etree, re), FastAPI/Starlette route, vanilla JS modules.

**Spec:** `docs/superpowers/specs/2026-11-22-library-names-design.md`

## Global Constraints

- English in code, comments, UI strings, commits, docs (`README.id.md` excepted).
- No network during conversion. No new dependency.
- Naming must never fail a conversion: any error while building the name gives `library_name = None`.
- `LANG` is two capital letters (`ID`, `EN`); the EPUB name has no device ending, XTC/XTCH keep `.<device>`.
- The CLI keeps today's output names. Old jobs (no `library_name`) keep their old download name.
- Every GUI text lives in `STRINGS` (`src/eco/web/strings.py`).

## Review Focus

- A title made only of forbidden characters, or empty after cleaning: no name (`None`), the download keeps the old name.
- A Windows reserved name (`CON`, `NUL`, `COM1`...) as the whole title: it gets a suffix and stays downloadable.
- A very long title and author list: capped at 150 characters before the extension, cut at a word.
- An EPUB whose OPF is missing or malformed, or whose spine documents do not parse: the conversion still succeeds, `library_name` is `None`.
- `?name=library` on a job from before this change, or any other value of `name`: today's name, never a 4xx.

---

### Task 1: `eco/naming.py`, the name from book facts

**Files:**
- Create: `src/eco/naming.py`
- Modify: `src/eco/pdf/text.py` (add `sure_language`)
- Test: `tests/test_naming.py`

**Interfaces:**
- Produces:
  - `eco.pdf.text.sure_language(text: str, minimum: int = 20) -> str | None`: `"id"` or `"en"` as `detect_language` decides, or `None` when both stopword counts are below `minimum`.
  - `@dataclass(frozen=True) class BookFacts: title: str; authors: list[str]; language: str; text: str` (`language` is the metadata value, may be `""`).
  - `facts_from_epub(path: Path) -> BookFacts`: reads `META-INF/container.xml` -> OPF -> `dc:title` (first), every `dc:creator` (in order), `dc:language` (first), and the text of the spine's XHTML bodies in order (`itertext`, whitespace collapsed) until 200,000 characters. Raises on an unreadable EPUB (the caller catches).
  - `library_name(facts: BookFacts) -> str | None`: the name without extension.
  - `MAX_NAME = 150`.

- [ ] **Step 1: Write the failing tests** in `tests/test_naming.py`:

```python
from eco.naming import BookFacts, library_name

ID_TEXT = "yang dan di ini itu dengan untuk tidak dari dalam " * 5
EN_TEXT = "the and of to is in that for with it " * 5

def facts(title, authors=(), language="", text=ID_TEXT):
    return BookFacts(title, list(authors), language, text)

def test_language_comes_from_the_text_not_the_metadata():
    assert library_name(facts("Never Split the Difference", ["Chris Voss"], "en")) == (
        "ID - Never Split the Difference - Chris Voss")
    assert library_name(facts("Deep Work", ["Cal Newport"], "id", EN_TEXT)) == "EN - Deep Work - Cal Newport"

def test_unknown_text_uses_the_metadata_language_then_nothing():
    assert library_name(facts("Kokoro", ["Natsume Soseki"], "ja-JP", "猫")) == "JA - Kokoro - Natsume Soseki"
    assert library_name(facts("Kokoro", ["Natsume Soseki"], "", "猫")) == "Kokoro - Natsume Soseki"

def test_last_first_is_turned_round():
    assert library_name(facts("The 7 Habits", ["Covey, Stephen"], text=EN_TEXT)) == "EN - The 7 Habits - Stephen Covey"

def test_several_authors_give_the_first_and_a_marker_in_the_book_language():
    many = "Chad Maurice, Jeremy Thompson and William Copeland"
    assert library_name(facts("Threat Hunting", [many], text=EN_TEXT)) == "EN - Threat Hunting - Chad Maurice et al."
    assert library_name(facts("Buku", ["Ani", "Budi"])) == "ID - Buku - Ani dkk."

def test_a_title_ending_in_a_name_gives_the_author_when_there_is_none():
    assert library_name(facts("Bicara itu ada seninya - Oh Su Hyang")) == (
        "ID - Bicara itu ada seninya - Oh Su Hyang")
    assert library_name(facts("Catatan - jilid dua")) == "ID - Catatan - jilid dua"  # not a name: stays

def test_no_author_leaves_the_part_out():
    assert library_name(facts("Atomic Habits")) == "ID - Atomic Habits"

def test_windows_forbidden_characters():
    assert library_name(facts('Atomic Habits: Perubahan "Kecil"? a/b', ["James Clear"])) == (
        "ID - Atomic Habits - Perubahan Kecil ab - James Clear")

def test_no_title_left_gives_no_name():
    assert library_name(facts(':?*', ["X"])) is None
    assert library_name(facts("   ")) is None

def test_reserved_name_and_trailing_dots():
    assert library_name(facts("CON", text="猫")) == "CON_"
    assert library_name(facts("Title...", text="猫")) == "Title"

def test_long_names_are_cut_at_a_word():
    name = library_name(facts("word " * 60, ["Ani"]))
    assert len(name) <= 150 and name.endswith(" - Ani") and "  " not in name
```

And a `facts_from_epub` test built on the existing EPUB fixture helper (`tests/fixtures/make.py`): build a small EPUB with two creators and a language, assert `title`, `authors == [first, second]`, `language`, and that a body word appears in `text`.

- [ ] **Step 2: Run** `uv run pytest tests/test_naming.py -q`. Expected: FAIL, `ModuleNotFoundError: eco.naming`.

- [ ] **Step 3: Implement** `sure_language` beside `detect_language` in `src/eco/pdf/text.py`, and `src/eco/naming.py`. Rules the tests do not fully pin:
  - Authors: with more than one `dc:creator`, the first plus the marker. With one string: one comma, no ` and `/`&`/`;`, and a single-word left side -> `Last, First` turned round; otherwise split on `,`, ` and `, `&`, `;` and, when that gives more than one, the first plus the marker. Marker: ` dkk.` when the language part is `ID`, else ` et al.`.
  - Title-to-author: only with no author, the part after the last ` - ` when it is 2 to 4 words that each start with a capital letter.
  - Cleaning (title and author separately): `:` -> ` - `; `" ? / \ * < > |` and control characters dropped; whitespace and repeated ` - ` collapsed; leading/trailing spaces, dots and dashes stripped. Empty title -> `None`.
  - Reserved names (`CON PRN AUX NUL COM1-9 LPT1-9`, any case) as the whole name get `_` appended.
  - Cap: if over `MAX_NAME`, cut the title at the last space that fits with the other parts.

- [ ] **Step 4: Run** `uv run pytest tests/test_naming.py -q`. Expected: PASS. Then `uv run ruff check && uv run ruff format`.

- [ ] **Step 5: Commit** `feat(naming): library names from book facts`.

---

### Task 2: the name travels from the pipeline into the job

**Files:**
- Modify: `src/eco/pipeline.py` (`Result`, end of `convert_file`)
- Modify: `src/eco/web/jobs.py` (`JobFile`, the `done` event in `_work`, `_record`)
- Modify: `tests/web/fakes.py` (`fake_work` sends a `library_name`)
- Test: `tests/test_pipeline.py`, `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `BookFacts`, `facts_from_epub`, `library_name` (Task 1).
- Produces: `Result.library_name: str | None = None` (last field); `JobFile.library_name: str | None = None` (last field, so old `job.json` files load); the worker's `done` event key `"library_name"`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_pipeline.py::test_the_result_carries_a_library_name`: a Markdown file with front matter `title: "Buku Saya"`, `author: "Ani"` and an Indonesian body sentence; `convert_file(...)` -> `result.library_name == "ID - Buku Saya - Ani"`.
  - `test_options_title_and_author_win_in_the_library_name`: an EPUB input (build with the fixture helper) and `Options(title="Lain", author="Budi")` -> the name has `Lain` and `Budi`.
  - `test_an_unreadable_epub_for_naming_still_converts`: monkeypatch `eco.pipeline.facts_from_epub` to raise `ValueError`; an EPUB input still converts and `result.library_name is None`.
  - `tests/web/test_jobs.py`: after a fake job ends, `job.json`'s file has `"library_name"` equal to what `fake_work` sent; a `job.json` without the key loads with `library_name is None`.

- [ ] **Step 2: Run** `uv run pytest tests/test_pipeline.py tests/web/test_jobs.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.** In `convert_file`, after the outputs are written: facts are `facts_from_epub(path)` for an EPUB input, else `BookFacts(source.meta.get("title",""), [source.meta["author"]] if source.meta.get("author") else [], source.meta.get("language",""), source.markdown)`; then `options.title` / `options.author` replace title / authors when set; `library_name(facts)`. Wrap the facts and the name in `try/except Exception` -> `None` (naming must never fail a conversion). In `_work` add `"library_name": result.library_name` to the `done` event; in `_record` store `event.get("library_name")`.

- [ ] **Step 4: Run** `uv run pytest tests/test_pipeline.py tests/web -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(naming): store the library name with each converted file`.

---

### Task 3: download under the library name

**Files:**
- Modify: `src/eco/web/app.py` (`download` route, the route list in the module docstring)
- Test: `tests/web/test_api.py`

**Interfaces:**
- Consumes: `JobFile.library_name` (Task 2).
- Produces: `GET /api/jobs/{id}/files/{n}/download/{fmt}?name=library`.

- [ ] **Step 1: Write the failing tests** (use the `finished` fixture; `fake_work` now sends `library_name`, e.g. `f"ID - {path.stem} - Ani"`):
  - `?name=library` on the EPUB -> `filename*=UTF-8''` of `ID - Bab Ü - Ani.epub` (and the ASCII `filename` with `_` for `Ü`).
  - an XTCH output (make `fake_work` write an `xtch` too for one file, or a dedicated job) -> `ID - notes - Ani.x4.xtch`, device from the job's options.
  - no parameter -> today's name (existing tests stay green); `?name=other` -> today's name; a file with `library_name` `None` and `?name=library` -> today's name, status 200.

- [ ] **Step 2: Run** `uv run pytest tests/web/test_api.py -q -k download`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** in `download(job_id, n, fmt, name: str | None = None)`: when `name == "library"` and the file has a `library_name`, the sent name is `f"{library_name}.epub"` for `fmt == "epub"`, else `f"{library_name}.{info.options['device']}.{fmt}"`; otherwise `path.name`. Always through `_disposition`.

- [ ] **Step 4: Run** `uv run pytest tests/web -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(web): download under the library name`.

---

### Task 4: the toggle in Export, docs

**Files:**
- Modify: `src/eco/web/templates/index.html` (Export section, above `#export-files`)
- Modify: `src/eco/web/static/review.js` (`renderExport`)
- Modify: `src/eco/web/static/app.js` (toggle listener)
- Modify: `src/eco/web/static/core.js` (`URLS.fileDownload` gains an optional `library` flag)
- Modify: `src/eco/web/strings.py`, `src/eco/web/static/app.css` (only if the row needs a style)
- Modify: `README.md`, `README.id.md` (Export: one sentence), `AGENTS.md` (architecture map: `src/eco/naming.py`), `docs/decisions.md`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `JobFile.library_name` in the job JSON; the `?name=library` route (Task 3).
- Produces: checkbox `#export-library-names`; strings `export_library_names` = `"Name files as Language - Title - Author"`; `localStorage` key `eco.libraryNames` (`"1"` on).

- [ ] **Step 1: Write the failing tests** in `tests/web/test_app.py`, in the style of the existing Export tests (`function_body(source(...), "renderExport")`, template string checks):
  - the template has `id="export-library-names"` of `type="checkbox"` before `id="export-files"`, labelled with `strings.export_library_names`;
  - `STRINGS["export_library_names"] == "Name files as Language - Title - Author"`;
  - `renderExport` uses `library_name`, and the download link passes the library flag to `URLS.fileDownload`;
  - every `localStorage` access in the static JS sits inside a `try` block.

- [ ] **Step 2: Run** `uv run pytest tests/web/test_app.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.**
  - `URLS.fileDownload(id, n, format, library = false)` appends `?name=library` when `library`.
  - The toggle: off on first use; its state is read from and written to `localStorage` in try/catch (a failure means off); a change re-renders Export.
  - The toggle is hidden when no reviewed file has a `library_name` (old jobs).
  - While on, each row with a `library_name` shows the name it downloads under (`ID - Title - Author.epub`, `... .x4-pro.xtch`, same ending rule as Task 3) under the file name, and its link uses the flag.
  - Docs: README Export sentence (both languages), AGENTS.md map line `src/eco/naming.py  BookFacts, facts_from_epub(), library_name() (download names)`, a dated entry in `docs/decisions.md` (the toggle, the parts, off by default, the CLI unchanged).

- [ ] **Step 4: Run** `uv run pytest tests -q`, `uv run ruff check`, `uv run ruff format --check`. Expected: all PASS.

- [ ] **Step 5: Check in the real app:** start the GUI on a free port with a scratch data folder, convert one Indonesian EPUB, turn the toggle on in Export, and confirm the row shows `ID - ... .epub` and the download arrives under that name.

- [ ] **Step 6: Commit** `feat(web): Export toggle for library names`.
