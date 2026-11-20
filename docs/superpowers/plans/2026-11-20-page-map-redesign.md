# Page map GUI redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the eco web GUI end to end around the page map (Select, Convert, Review, Export) as the spec describes, with the small additive backend changes it needs.

**Architecture:** Backend first: richer events (page numbers, a book event, timestamps), scanned/blank lists from inspect, and a recorded EPUBCheck outcome. Then the frontend in the existing no-framework stack: new tokens and font, one new module `pagemap.js` shared by three screens, then one task per screen, then a responsive/accessibility pass with browser checks.

**Tech Stack:** Python 3.12, FastAPI, pytest, Ruff; vanilla ES modules, HTML (Jinja template), CSS. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-20-end-to-end-redesign-design.md`. Mockups: the private Design canvas named in the spec (row "End to end, direction C"). Read the spec before each task; its values win over the mockup.

## Global Constraints

- Worktree: `D:/Tools/epub-converter/eco/.claude/worktrees/redesign-page-map`, branch `redesign-page-map`. The main checkout (`D:/Tools/epub-converter/eco`) has unrelated uncommitted changes: never touch it.
- Commands (Bash tool): `export PATH="$HOME/.local/bin:$PATH"` first; `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`.
- Every UI text goes in `src/eco/web/strings.py`, in plain English, no emoji. Code, comments and commits in English.
- CSP stays `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'`: no inline `style=` in the template, no `setAttribute('style')`, no `innerHTML`. Setting `element.style.<prop>` from JS (CSSOM) is allowed and already used.
- No network from the page; no `http://` or `https://` in the template, CSS or JS (`test_no_external_address_in_the_page_its_style_or_its_script`).
- Persistence changes are additive only; a `job.json` or `events.jsonl` written before this branch must still load and render.
- Tokens, type, radii and copy exactly as the spec's "Visual system" section.
- One blue (`.primary`) button visible per screen at a time.
- Status is never color-only: every state has a word.
- Touch targets ≥ 44×44 px; visible focus ring 2 px `#1D4ED8`, 2 px offset.
- Tests for the frontend follow the existing pattern in `tests/web/test_app.py`: assertions on the rendered page (`local(tmp_path).get("/").text`, `stage_markup`) and on module source (`source("app.js")`, `function_body`). There is no JS runtime in CI.

## Review Focus

1. **Old jobs** (written before this branch: no `book` event, no `t`, no `page` in page events, no `epubcheck`): Convert and Review render without a page map or durations, and Export shows no EPUBCheck line, with no script error. Owner: Task 7 (Convert) and Task 9 (Export); backend loading in Task 3.
2. **A rebuild (Apply to book) reuses the extraction and sends no read/layout/fix events**: those stages show "Already done", the percent does not stall below 100, and Review comes back on the same file and page. Owner: Task 7 and Task 8.
3. **Markdown and EPUB inputs** (no source pages, findings all on page 0): no page map on Select/Convert, Review strip with device pages and no finding bars, findings labelled "Whole book". Owner: Tasks 6, 7, 8.
4. **A multi-file job where a later file fails or the job is cancelled while the user is in Review**: Review stays, the top bar says what happened in text, Export opens once every file has ended and the successful ones are reviewed. Owner: Task 8.
5. **A very large PDF (2000+ pages)**: at most 1500 squares drawn, squares labelled with page ranges, the Review strip groups pages, and updates batch per animation frame. Owner: Task 5.

---

### Task 1: Page numbers and the book event

**Files:**
- Modify: `src/eco/events.py`
- Modify: `src/eco/pipeline.py` (`_read`, `_layout.on_page`, `extract_pdf`, `page_book`)
- Modify: `src/eco/web/jobs.py` (`_event`)
- Test: `tests/test_pipeline.py`, `tests/web/test_jobs.py`

**Interfaces:**
- Produces: `PageEvent(done: int, total: int, page: int | None = None)`; `BookEvent(pages: int, scanned: tuple[int, ...], blank: tuple[int, ...])`; `Event = StageEvent | PageEvent | FindingEvent | BookEvent`. Browser dicts: `{"type": "page", "done", "total", "page"}` and `{"type": "book", "pages", "scanned": [...], "blank": [...]}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py` (reuse the file's existing PDF fixtures and event capture):

```python
def test_layout_page_events_name_the_page_they_finished(...):
    # Docling path, 2-page fixture: the existing assertion at line ~198 becomes
    assert [e for e in seen if isinstance(e, PageEvent)] == [PageEvent(1, 2, 1), PageEvent(2, 2, 2)]

def test_a_pdf_conversion_sends_one_book_event_after_read(...):
    books = [e for e in seen if isinstance(e, BookEvent)]
    assert books == [BookEvent(pages=<fixture pages>, scanned=<expected>, blank=<expected>)]
    # it comes after read finished and before layout started
    assert seen.index(StageEvent("read", "finished")) < seen.index(books[0]) < seen.index(StageEvent("layout", "started"))

def test_a_reused_extraction_sends_no_book_event(...):
    # second convert_file of the same PDF with the same data_dir
    assert not [e for e in seen_second if isinstance(e, BookEvent)]
```

Update the other `PageEvent(...)` equality assertions in this file (lines ~350, ~377, ~450) to carry the page number. In `tests/web/test_jobs.py`:

```python
def test_page_and_book_events_reach_the_browser_dict():
    assert jobs._event(PageEvent(3, 10, 4)) == {"type": "page", "done": 3, "total": 10, "page": 4}
    assert jobs._event(BookEvent(5, (2,), (5,))) == {"type": "book", "pages": 5, "scanned": [2], "blank": [5]}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_pipeline.py tests/web/test_jobs.py -q`
Expected: FAIL (`BookEvent` cannot be imported; PageEvent has no `page`).

- [ ] **Step 3: Implement**

`events.py`: add the field with default `None` and the `BookEvent` dataclass (frozen, like the others). `pipeline.py`: `_read` emits `BookEvent(len(infos), tuple(scanned numbers), tuple(blank numbers))` after its stage closes (outside the `with _stage` block) and still returns `infos`; `on_page(number)` emits `PageEvent(len(reported), len(numbers), number)`; `page_book` emits `PageEvent(done, len(numbers), number)`. `extract_pdf`'s reuse branch stays as it is (no book event). `jobs._event` adds `"page": e.page` and a `BookEvent` branch with lists.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pipeline.py tests/web/test_jobs.py tests/web/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eco/events.py src/eco/pipeline.py src/eco/web/jobs.py tests/test_pipeline.py tests/web/test_jobs.py
git commit -m "feat: report finished page numbers and a book event"
```

### Task 2: Event timestamps and scanned/blank lists from inspect

**Files:**
- Modify: `src/eco/web/jobs.py` (`Runner._publish`)
- Modify: `src/eco/web/preview.py` (`describe_pdf`)
- Test: `tests/web/test_jobs.py`, `tests/web/test_inspect.py`

**Interfaces:**
- Produces: every event in `events.jsonl` and on the stream has `"t": float` (server `time.time()`), set once in `_publish` when absent (a replayed event keeps its stored `t`). `/api/inspect` answers `{"pages", "scanned_pages", "scanned": [int], "blank": [int], "seconds_per_page"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_jobs.py — with the existing fake_work runner helper
def test_every_stored_and_streamed_event_has_a_server_time(...):
    events = store.events(job_id)
    assert events and all(isinstance(e["t"], float) for e in events)
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)

# tests/web/test_inspect.py
def test_the_answer_lists_the_scanned_and_blank_pages(tmp_path, mixed):
    path = tmp_path / "mixed.pdf"; path.write_bytes(mixed)
    infos = inspect_pdf(path)
    answer = inspect(client(tmp_path / "data"), "mixed.pdf", mixed).json()
    assert answer["scanned"] == [i.number for i in infos if i.is_scanned]
    assert answer["blank"] == [i.number for i in infos if i.is_blank]
```

Update `test_the_answer_is_the_counts_and_the_provisional_rates_and_nothing_else` to the new exact dict (`"scanned": [], "blank": []` for the digital fixture) and rename it `test_the_answer_is_the_counts_the_page_lists_and_the_rates`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/web/test_jobs.py tests/web/test_inspect.py -q` — Expected: FAIL (no `t`, no `scanned`).

- [ ] **Step 3: Implement** — `_publish`: `event.setdefault("t", time.time())` before `append_event`. `describe_pdf`: add the two lists from `infos`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/web -q` — Expected: PASS (fix any test that compares whole event dicts by ignoring `t`).

- [ ] **Step 5: Commit** — `git commit -m "feat: time every job event and list scanned and blank pages"`

### Task 3: Record the EPUBCheck outcome

**Files:**
- Modify: `src/eco/epub/validator.py`, `src/eco/pipeline.py` (`Result`, `convert_file`), `src/eco/web/jobs.py` (`JobFile`, `_work`, `Runner._record`), `src/eco/web/app.py` (`_public`)
- Test: `tests/epub/test_validator.py`, `tests/test_pipeline.py`, `tests/web/test_jobs.py`, `tests/web/test_api.py`

**Interfaces:**
- Produces: `validate_epub(path) -> list[str] | None` (None: no validator configured, nothing ran). `Result.epubcheck: str | None` — `"passed"`, `"passed_with_warnings"`, `"not_run"`, or `None` when no EPUB was made. `JobFile.epubcheck: str | None = None` (last field, defaulted, so old `job.json` loads). The `file` done event and `_public` files carry `"epubcheck"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/epub/test_validator.py
# test_source_install_without_tools_keeps_converting: assert validate_epub(...) is None
# test_bundled_tools_are_used_without_host_java: still == []

# tests/test_pipeline.py — Markdown fixture, monkeypatch eco.pipeline.validate_epub
@pytest.mark.parametrize("answer, outcome", [(None, "not_run"), ([], "passed"), (["WARNING(X): y"], "passed_with_warnings")])
def test_the_result_names_the_epubcheck_outcome(monkeypatch, tmp_path, answer, outcome):
    ...
    assert result.epubcheck == outcome

def test_an_xtc_only_result_has_no_epubcheck_outcome(...):
    assert result.epubcheck is None

# tests/web/test_jobs.py
def test_a_job_json_without_epubcheck_still_loads(tmp_path):
    # write a job.json whose file dicts lack "epubcheck"; store.get(id).files[0].epubcheck is None

# tests/web/test_api.py
def test_the_public_job_shows_each_files_epubcheck_outcome(...):
    assert client.get(f"/api/jobs/{id}").json()["files"][0]["epubcheck"] in ("passed", "not_run", ...)
```

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/epub/test_validator.py tests/test_pipeline.py tests/web -q`; Expected: FAIL.

- [ ] **Step 3: Implement** — `validate_epub` returns `None` where it returns `[]` today because `_tools()` is None. `convert_file` keeps the warnings list (`warnings or []` for findings) and sets the outcome; `Result` gains the field (last, default `None`). `_work` adds `"epubcheck": result.epubcheck` to the done event; `_record` stores `event.get("epubcheck")`; `_public` adds `"epubcheck": f.epubcheck`. `_public_event` needs no change.

- [ ] **Step 4: Run all fast tests** — `uv run pytest -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat: record whether EPUBCheck passed, warned or did not run"`

### Task 4: Previews of a finished file while the next one converts

**Files:**
- Test: `tests/web/test_preview.py` (or `test_api.py`, where a running job with a fake worker already exists)
- Modify only if the test fails: `src/eco/web/preview.py`

- [ ] **Step 1: Write the test** `test_a_finished_file_previews_while_a_later_file_converts`: a two-file job with a fake worker that finishes file 0 (real output from a Markdown fixture) and then blocks on file 1 (use or add a fake in `tests/web/fakes.py` that waits on a flag file). While the job is `running`: `GET /api/jobs/{id}/files/0/pages?format=epub` → 200 with `device_pages > 0`, and `GET .../files/0/preview/epub/1.png` → 200 `image/png`.
- [ ] **Step 2: Run it** — `uv run pytest tests/web/test_preview.py -k later_file -q`. Expected: PASS (the builder check expects it to pass). If it fails, fix the narrowest cause in `Previews` and rerun.
- [ ] **Step 3: Commit** — `git commit -m "test: preview a finished file while the job runs"`

### Task 5: Visual foundation, shell and the page map module

**Files:**
- Create: `src/eco/web/static/fonts/InterVariable.woff2`, `src/eco/web/static/fonts/OFL.txt`
- Create: `src/eco/web/static/pagemap.js`
- Modify: `src/eco/web/static/app.css` (tokens, base, header, stepper; remove the Guided Workspace block), `src/eco/web/templates/index.html` (header only), `src/eco/web/static/core.js` (stepper links), `src/eco/web/app.py` (`mimetypes.add_type("font/woff2", ".woff2")` next to the `.js` one), `DESIGN.md` (rewrite), `AGENTS.md` (architecture map line for `pagemap.js` and the fonts folder)
- Modify: `tests/web/test_app.py` (`source("app.js")` part list gains `"pagemap.js"` before `"app.js"`)
- Test: `tests/web/test_app.py`

**Interfaces:**
- Produces in `pagemap.js` (pure functions plus two DOM renderers):
  - `squareSize(pages: number) -> 12 | 8` (12 up to 600 pages, else 8).
  - `pagesPerSquare(pages: number) -> number` (`1` up to 1500 pages, else `Math.ceil(pages / 1500)`).
  - `mapCells(book: {pages, scanned, blank}, progress: {done: Set<number>, current: number|null}, findings: number[], mode: 'select'|'convert') -> Array<{state: 'digital'|'scanned'|'done'|'now'|'todo'|'finding', label: string}>` — one cell per square; a grouped square takes the "worst" state in this order: finding, now, todo, done (convert) or scanned, digital (select). Labels use strings `pagemap_page` ("Page {n}"), `pagemap_pages` ("Pages {first}–{last}"), suffixes `pagemap_blank`, `pagemap_scanned`, `pagemap_finding`.
  - `renderPageMap(container: HTMLElement, cells, size)` — reuses existing `<span>` children when the count is unchanged and only swaps `className` (`pm-cell pm-<state>`) and `title`; sets `container.style.setProperty('--pm-size', size + 'px')`.
  - `stripBars(pages: number, findings: number[], current: number) -> Array<{kind: 'plain'|'finding'|'current', first: number, last: number}>` (groups so at most 600 bars).
  - `renderStrip(container: HTMLElement, bars)` — spans with classes `strip-bar strip-<kind>`.
- Produces in `core.js`: `stepItem` renders the Convert step as a link (`#convert`) while `state.job` is active and `state.stage === 'review'`, calling `showProcessing()`; Review as a link from Export, calling `backToReview()`.

- [ ] **Step 1: Write the failing tests** (in `tests/web/test_app.py`)

```python
def test_the_page_uses_the_bundled_inter_font_and_the_new_tokens():
    css = source("app.css")
    assert "url(\"/static/fonts/InterVariable.woff2\")" in css or "url(fonts/InterVariable.woff2)" in css
    for token in ("#FAFAF9", "#18181B", "#52525B", "#71717A", "#1D4ED8", "#15803D", "#B45309", "#F59E0B", "#B91C1C", "#3F3F46", "#6D28D9"):
        assert token.lower() in css.lower()
    assert "Guided Workspace" not in css

def test_the_font_is_served_as_woff2(tmp_path):
    r = local(tmp_path).get("/static/fonts/InterVariable.woff2")
    assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"

def test_page_map_module_keeps_large_books_to_1500_squares():
    js = source("app.js")
    assert "export function squareSize" in js and "export function pagesPerSquare" in js
    assert "1500" in function_body(js, "pagesPerSquare")
    assert "600" in function_body(js, "squareSize")
    assert "requestAnimationFrame" not in function_body(js, "mapCells")  # pure

def test_the_header_names_the_four_steps_and_runs_locally(tmp_path):
    html = local(tmp_path).get("/").text
    assert STRINGS["runs_locally"] == "Runs on this computer" and "strings.runs_locally" in source("index.html")
```

Delete or rewrite the tests that pin the Guided Workspace markup and that this task makes obsolete (stepper wording stays; `test_step_navigation_wraps_in_document_flow` stays).

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/web/test_app.py -q`.

- [ ] **Step 3: Get Inter** — download the Inter 4.x release zip from the official `rsms/inter` GitHub releases page (about 1–2 MB; tell the orchestrator the measured size first if it is over 5 MB), copy `InterVariable.woff2` and `LICENSE.txt` (as `OFL.txt`) into `static/fonts/`. No other file from the zip.

- [ ] **Step 4: Implement** — CSS: `@font-face` for Inter (weight range 100 900, `font-display: swap`), `:root` custom properties named after the spec's tokens (`--bg`, `--panel`, `--border`, `--control-border`, `--text`, `--muted`, `--subtle`, `--accent`, `--success`, `--warning-text`, `--warning-mark`, `--error`, `--page-done`, `--page-waiting`, `--page-scanned`, `--page-digital`, `--bezel`, `--eink`), base type (14 px/1.5, tabular numbers class `.num`), header and stepper per the spec's Shared shell, `.pm-grid` (CSS grid `repeat(auto-fill, var(--pm-size))`, gap 4 px at 12 px, 3 px at 8–10 px), `.pm-cell` and its state classes, `.strip`, `.strip-bar` and kinds. `pagemap.js` per the interfaces. DESIGN.md: replace tokens, type and radii with the spec's tables; keep its Rules list and add "Status is never color-only" and "The page map is the shared progress picture". New strings: `runs_locally`, `pagemap_page`, `pagemap_pages`, `pagemap_blank`, `pagemap_scanned`, `pagemap_finding`.

- [ ] **Step 5: Run the web tests and Ruff** — `uv run pytest tests/web -q && uv run ruff check && uv run ruff format --check` — Expected: PASS.

- [ ] **Step 6: Commit** — `git commit -m "feat: page map module, Inter and the new visual tokens"`

### Task 6: Select

**Files:**
- Modify: `src/eco/web/templates/index.html` (`stage-select`; remove `stage-setup`), `src/eco/web/static/start.js`, `src/eco/web/static/core.js` (`showStart`, `SECTIONS`, `state.skipModels` removed), `src/eco/web/static/app.js` (bindings), `src/eco/web/static/app.css`, `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`, `tests/web/test_setup.py` (only where it asserts the gate markup)

**Interfaces:**
- Consumes: `/api/inspect` lists (Task 2); `mapCells`, `renderPageMap`, `squareSize` (Task 5).
- Produces: `readOptions()` builds `style` from the chosen saved style (`#select-style`, the default preselected) and no longer reads `#font-size`, `#embed-focus`, `#embed-focus-strength` (those elements are removed). Element ids kept: `drop-zone`, `file-input`, `drop-error`, `file-list`, `device`, `size`, `advanced`, `firmware`, `firmware-advice`, `ocr`, `mode`, `mode-hint`, `book-title`, `book-author`, `book-lang`, `font-library` and its children, `start`, `start-hint`, `recent-title`, `recent-status`, `recent`, `models-note`, `models-text`, `models-download`. New ids: `select-style`, `start-estimate`, `models-ipv4`, `models-progress`, `models-log`, `models-error`. `size` becomes a radio group `input[name="size"]` inside a fieldset with id `size` kept on the fieldset; `readOptions` reads the checked radio.

- [ ] **Step 1: Write the failing tests**

```python
def test_select_has_the_book_column_and_four_reading_settings(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    for id_ in ("drop-zone", "file-list", "device", "select-style", "size", "advanced", "start", "start-estimate", "recent"):
        assert f'id="{id_}"' in select
    assert len(re.findall(r'name="output"', select)) == 2
    assert 'id="font-size"' not in select and 'id="embed-focus"' not in select

def test_there_is_no_setup_gate_and_the_models_notice_carries_the_download(tmp_path):
    html = local(tmp_path).get("/").text
    assert 'id="stage-setup"' not in html
    note = stage_markup(html, "select").split('id="models-note"', 1)[1]
    for id_ in ("models-download", "models-ipv4", "models-progress", "models-log", "models-error"):
        assert f'id="{id_}"' in note
    assert "showSetup" not in source("app.js")

def test_a_pdf_row_draws_its_page_map_from_the_inspect_lists():
    body = function_body(source("app.js"), "renderFiles")
    assert "mapCells(" in body and "'select'" in body and "renderPageMap(" in body
    assert "role: 'img'" in source("app.js")

def test_the_start_options_take_style_values_from_the_chosen_style():
    body = function_body(source("app.js"), "readOptions")
    assert "$('font-size')" not in body and "$('embed-focus')" not in body
    assert "selectedStyle" in body
```

Strings to add (exact): `workspace_title` "Convert a book", `workspace_intro` "Add a PDF, Markdown or EPUB file and choose where you will read it.", `drop_text` "Drop files here or choose files", `drop_hint` "PDF, Markdown or EPUB, up to {mb} MB", `reading_style_label` "Reading style", `reading_style_hint` "You can fine-tune it in Review.", `output_epub_hint` "Reflowable text", `output_xtc_hint` "Pages for the X4", `more_settings` "More settings", `more_settings_hint` "firmware, OCR, layout, title and author, fonts", `start_estimate` "About {time} in total on this computer", `legend_digital` "Digital text", `legend_scanned` "Scanned, read with OCR", `legend_scanned_no_ocr` "Scanned, no OCR", `pagemap_summary` "{pages} pages, {scanned} scanned", `models_needed` "PDFs need the AI models ({mb} MB, downloaded once).", `recent_open` "Open", `recent_details` "Details". Reuse the existing setup and models strings for the download states.

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/web/test_app.py tests/web/test_setup.py -q`.

- [ ] **Step 3: Implement** — markup and CSS per the spec's Screen 1 and the `1 · Select` board; the two-column layout collapses below 900 px. Move the setup download logic (`startDownload`, `listenSetup`, `setupEnded`, IPv4 retry) to drive the notice elements; `showStart()` always calls `showSelect()`. `#select-style` lists `/api/styles` (default selected; label "name (default)"), and `selectedStyle` holds the fetched style object used by `readOptions()`. PDF rows: after the scan answers, render the map (`role="img"`, `aria-label` from `pagemap_summary`) and the legend; Markdown/EPUB rows have none. The start estimate sums `estimateSeconds` over the rows. Recent rows: name, date and outputs, status word with class `status-<status>`, and the Open/Details link.

- [ ] **Step 4: Run the web tests** — `uv run pytest tests/web -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat: Select with page maps, reading style and inline model download"`

### Task 7: Convert

**Files:**
- Modify: `src/eco/web/templates/index.html` (`stage-processing`), `src/eco/web/static/job.js`, `src/eco/web/static/core.js` (`STAGE_NAME` short labels), `src/eco/web/static/app.css`, `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: event `page.page`, `book`, `t` (Tasks 1–2); file done event `outputs`, `sizes`, `epubcheck` (Task 3); `mapCells`, `renderPageMap` (Task 5).
- Produces: per-file run state `newFileRun()` gains `book: null | {pages, scanned, blank}`, `donePages: Set<number>`, `stageTimes: {[stage]: {start: number|null, end: number|null}}`, `startedAt: number|null`, `shown: number` (the never-decreasing percent). `stagesFor(file, options)` follows the spec's rules: `epub` stage only when EPUB output is chosen and the input is not EPUB; `optimize` only with EPUB output; `fix` not for page-images PDFs; `xtc` only with an XTC format; plus any stage seen in events but not expected (`file.stages` keys) appended in `STAGES` order. `progressFraction(file, names) -> number` implements the spec's Progress model with weights `{read: .05, layout: .55, fix: .15, epub: .10, optimize: .08, xtc: .07}` renormalized over `names`, 0.5 for a running stage without page events, capped at 0.99 until the file is done. `apply()` on a file done event copies `outputs`, `sizes`, `epubcheck` into `state.job.files[index]`; when it is the first converted file and `state.stage === 'processing'`, it calls `showReview()` (only once per job; later files never switch screens).

- [ ] **Step 1: Write the failing tests**

```python
def test_convert_has_queue_title_stage_bar_page_map_and_findings(tmp_path):
    conv = stage_markup(local(tmp_path).get("/").text, "processing")
    for id_ in ("file-queue", "file-title", "file-meta", "percent", "time-line", "cancel", "stage-bar", "page-map", "page-map-title", "feed", "feed-empty", "process-error"):
        assert f'id="{id_}"' in conv
    assert 'aria-live="polite"' in conv

def test_stages_follow_the_pipeline_rules():
    body = function_body(source("app.js"), "stagesFor")
    for rule in ("'epub'", "'optimize'", "'fix'", "'xtc'", "STAGES"):
        assert rule in body

def test_progress_never_goes_back_and_never_shows_100_early():
    body = function_body(source("app.js"), "progressFraction")
    assert "0.55" in body and "0.99" in body
    assert "Math.max(file.shown" in source("app.js")

def test_only_warnings_are_counted_and_page_zero_is_the_whole_book():
    js = source("app.js")
    assert "level === 'warning'" in function_body(js, "renderFeed")
    assert "t('whole_book')" in js

def test_review_opens_once_when_the_first_file_is_done():
    body = function_body(source("app.js"), "apply")
    assert "state.job.files[event.index].outputs = event.outputs" in body
    assert "reviewOpened" in body

def test_failure_offers_try_again_only_when_nothing_converted(tmp_path):
    conv = stage_markup(local(tmp_path).get("/").text, "processing")
    assert 'id="process-try-again"' in conv and 'id="process-back"' in conv
```

Strings (exact): `queue_converting` "converting", `queue_next_short` "next", `queue_waiting_short` "waiting", `queue_done` "done", `queue_failed` "failed", `queue_cancelled` "cancelled", `time_line` "{left} · {elapsed} so far", `stage_done_in` "Done, {time}", `stage_pages` "{done} of {total} pages", `stage_in_progress` "In progress", `stage_waiting` "Waiting", `stage_stopped` "Stopped", `pages_read` "Pages · {done} of {total} read", `legend_done` "Done", `legend_working` "Working", `legend_waiting` "Waiting", `legend_finding` "Has a finding", `pagemap_caption` "Each square is one page. After the conversion, click a square to open that page in Review.", `review_opens` "Review opens by itself when this file is done.", `whole_book` "Whole book", `back_to_select` "Back to Select". Short stage labels for the bar: `stage_short_read` "Reading PDF", `stage_short_layout` "Page layout", `stage_short_fix` "Code, formulas, order", `stage_short_epub` "Building EPUB", `stage_short_optimize` "Optimizing", `stage_short_xtc` "Creating XTC" (keep the long `stage_*` strings for the screen-reader text).

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/web/test_app.py -q`.

- [ ] **Step 3: Implement** — markup and CSS per Screen 2 and the `2 · Convert` board. Stage bar segments use `flex-grow` = weight (set via `element.style.flexGrow`), fill width via `element.style.width`. The page map comes from `file.book` and `file.donePages` (fall back to filling pages `1..done` in order when `page` is absent); a page with a warning finding is `finding`; no `book` → map panel hidden and findings full width. Durations from `t`: `stageTimes` start/end; elapsed from the first event's `t` of the file. Cells are not clickable in this task; Task 8 adds the click. Live region text updates at most every 2 s (keep a timestamp). Failure and cancel per the spec; `process-try-again` calls the existing `tryAgain()`; `process-back` clears the hash. Reduced motion: no transitions on fills inside `@media (prefers-reduced-motion: reduce)`.

- [ ] **Step 4: Run the web tests** — `uv run pytest tests/web -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat: Convert with stage bar, live page map and honest progress"`

### Task 8: Review

**Files:**
- Modify: `src/eco/web/templates/index.html` (`stage-review`), `src/eco/web/static/review.js`, `src/eco/web/static/core.js` (`state.carry`, kept by `stopWork`), `src/eco/web/static/app.js`, `src/eco/web/static/app.css`, `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `stripBars`, `renderStrip` (Task 5); job file `outputs/sizes/epubcheck` live updates (Task 7).
- Produces: `state.carry: null | {fromJob: string, fileIndex, anchor, selected, format, view}` — set by `applyChanges()` right before `rebuild()`, consumed by `showReview()` when `state.job` is the rebuilt job (`job.id !== carry.fromJob` and the carry is younger than the route), then cleared. `review.notesOpen: boolean`. Ids kept: `review-title`, `chips`, `try-again`, `change-settings`, `approve-review`, `file-pick`, `review-file`, `review-note`, `review-grid`, `findings`, `findings-title`, `findings-list`, `findings-empty`, `source-pane` and children, `device-pane` and children, `prev`, `next`, `view-as`, `settings-panel` and all its controls, `review-dock` and its controls, `apply`. New ids: `page-strip`, `strip-label`, `review-status` (polite live region in the top bar), `review-progress-link`, `apply-status`, `discard`, `notes` (a `<details>` under the findings list), `notes-list`. `review-delete-job` and `review-delete-error` are removed (delete lives on Export only).

- [ ] **Step 1: Write the failing tests**

```python
def test_review_top_bar_strip_columns_and_style_panel(tmp_path):
    review = stage_markup(local(tmp_path).get("/").text, "review")
    for id_ in ("review-title", "chips", "approve-review", "review-status", "page-strip", "strip-label", "findings-list", "notes", "source-pane", "device-pane", "review-dock", "apply", "discard", "apply-status", "change-settings"):
        assert f'id="{id_}"' in review
    assert review.index('id="page-strip"') < review.index('id="findings"') < review.index('id="source-pane"') < review.index('id="device-pane"') < review.index('id="review-dock"')
    assert re.search(r'<div id="page-strip"[^>]*role="slider"', review)

def test_the_strip_is_a_keyboard_slider():
    js = source("app.js")
    body = function_body(js, "onStripKey")
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in body
    assert "aria-valuetext" in function_body(js, "renderPageStrip")

def test_dirty_style_makes_apply_the_one_primary_and_blocks_continue():
    body = function_body(source("app.js"), "updateApply")
    assert "classList.toggle('primary', dirty)" in body
    assert "$('approve-review').classList.toggle('primary', !dirty)" in body

def test_apply_carries_the_review_place_to_the_rebuilt_job():
    js = source("app.js")
    assert "state.carry = {" in function_body(js, "applyChanges")
    assert "state.carry" in function_body(js, "showReview")
    assert "carry" not in function_body(js, "stopWork")

def test_apply_waits_until_every_file_has_converted():
    assert "isActive(state.job)" in function_body(source("app.js"), "updateApply")

def test_continue_goes_to_the_next_file_until_export_is_ready():
    js = source("app.js")
    assert "t('continue_next_file')" in js and "t('continue_to_export')" in js
    ready = function_body(js, "exportReady")
    assert "isActive(state.job)" in ready and "filter(isConverted)" in ready

def test_info_findings_are_notes_not_warnings():
    body = function_body(source("app.js"), "renderFindings")
    assert "level === 'warning'" in body and "$('notes')" in body
```

Update or delete the existing Guided Workspace Review tests that conflict (e.g. `test_export_guard_requires_every_successful_file_to_be_reviewed` gains the active check; delete-in-Review tests go).

Strings (exact): `continue_to_export` "Continue to export", `continue_next_file` "Continue to next file", `apply_or_discard` "Apply or discard your changes to continue", `apply_to_book` "Apply to book", `discard` "Discard", `changes_pending_one` "1 change shown in the preview, not yet in the files", `changes_pending_other` "{n} changes shown in the preview, not yet in the files", `applying_rebuild` "Applying… this rebuilds the files", `apply_wait` "Available when every file has converted", `changed` "changed", `strip_label` "Page {page} of {total}", `strip_hint` "Click any page to open it", `strip_value` "Page {page} of {total}", `strip_value_finding` "Page {page} of {total}, has a finding", `showing` "showing", `notes_title` "Notes ({n})", `ready_to_review` "{name} is ready to review", `converting_status` "Converting {name} · {percent}%", `show_progress` "Show progress", `file_failed_status` "{name} failed", `job_cancelled_status` "The conversion was cancelled", `original_pdf_page` "Original PDF · page {page}", `on_device` "On {device} · page {page} of {total}", `export_waiting_for` "{name} is still converting".

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/web/test_app.py -q`.

- [ ] **Step 3: Implement** — markup and CSS per Screen 3 and the `3 · Review` board, keeping today's preview loading, synchronized findings, live preview and Advanced typography panel. The strip counts source pages for PDFs (`review.pages.source_pages`) and device pages otherwise; clicking or keying a bar calls the existing source/device navigation (`firstPageFrom` for PDFs, `goTo` otherwise). A dock control whose value differs from `state.job.options.style` gets `· changed` in its `<output>`. `applyChanges()` keeps today's option building and `rebuild()`; it sets `state.carry` first. `showReview()` consumes the carry (file, anchor via `pageOfAnchor`, selected finding by page and message, format, view). Reviewed marks reset after a rebuild because every output changed. While `isActive(state.job)`, `#review-status` shows the converting/ready/failed/cancelled line with `#review-progress-link` calling `showProcessing()`, and `#apply` is disabled with `apply_wait`. The `left`/`right` page keys keep ignoring inputs, selects, buttons and the style panel. Add `openReviewAt(sourcePage: number)` in `review.js` (shows Review for the current file at the first device page of that source page) and bind it to clicks on the Convert page map's cells of a finished file (mouse shortcut; the cells stay out of the tab order); add an assertion `assert "openReviewAt(" in function_body(source("app.js"), "renderProcessing")` to Step 1.

- [ ] **Step 4: Run the web tests** — `uv run pytest tests/web -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat: Review with page strip, honest style status and carried place"`

### Task 9: Export

**Files:**
- Modify: `src/eco/web/templates/index.html` (`stage-export`), `src/eco/web/static/review.js` (`renderExport`), `src/eco/web/static/app.css`, `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `files[i].epubcheck` (Task 3), run findings (`kind === 'epubcheck_warning'`), `exportReady()` (Task 8).
- Produces: ids kept `export-title`, `export-status`, `export-files`, `back-to-review`, `delete-job`, `delete-error`; new `export-summary`, `export-checks`, `export-style`, `export-others`, `convert-another`.

- [ ] **Step 1: Write the failing tests**

```python
def test_export_has_files_checks_other_files_and_quiet_delete(tmp_path):
    export = stage_markup(local(tmp_path).get("/").text, "export")
    for id_ in ("export-title", "export-summary", "export-files", "export-checks", "export-style", "export-others", "back-to-review", "convert-another", "delete-job"):
        assert f'id="{id_}"' in export
    assert export.index('id="export-files"') < export.index('id="export-checks"') < export.index('id="delete-job"')

def test_export_states_each_epubcheck_outcome_and_omits_it_for_old_jobs():
    body = function_body(source("app.js"), "renderExport")
    for key in ("epubcheck_passed", "epubcheck_warnings", "epubcheck_not_run"):
        assert f"'{key}" in body
    assert "info.epubcheck" in body
    assert STRINGS["epubcheck_not_run"] == "EPUBCheck did not run, so this EPUB was not validated."

def test_export_restates_style_values_not_a_name():
    assert "style_applied" in function_body(source("app.js"), "renderExport")
```

Strings (exact): `export_title` "Ready to download", `export_summary` "{name} · {pages} · reviewed, {findings} · converted in {time}", `findings_seen_one` "1 finding seen", `findings_seen_other` "{n} findings seen", `epub_description` "EPUB · reflowable text · {size}, down from {before}", `xtc_description` "XTC · {kind} for {device} · {size}", `epubcheck_passed` "EPUBCheck passed.", `epubcheck_warnings_one` "EPUBCheck passed with 1 warning.", `epubcheck_warnings_other` "EPUBCheck passed with {n} warnings.", `epubcheck_not_run` "EPUBCheck did not run, so this EPUB was not validated.", `style_applied` "Reading style applied: {values}", `checks_title` "Checks", `other_files_title` "Other files", `waiting_review` "converted, waiting for review", `review_it` "Review it", `convert_another` "Convert another book", `delete_this` "Delete this conversion".

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/web/test_app.py -q`.

- [ ] **Step 3: Implement** — markup and CSS per Screen 4 and the `4 · Export` board; the first output's download link is `.primary`, the others `.secondary`; `export-others` lists files of the job that are not reviewed (link to that file in Review) or still converting; `convert-another` clears the hash. Delete keeps today's confirm and error handling.

- [ ] **Step 4: Run the web tests** — `uv run pytest tests/web -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat: Export with checks, other files and quiet delete"`

### Task 10: Responsive, accessibility and browser verification

**Files:**
- Modify: `src/eco/web/static/app.css`, any template or module the checks show broken
- Modify: `docs/decisions.md` (one dated line: the redesign shipped, and any spec value the builder changed with its reason)
- Test: `tests/web/test_app.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_layouts_collapse_at_900_and_600_and_keep_touch_targets():
    css = source("app.css")
    assert "@media (max-width: 900px)" in css and "@media (max-width: 600px)" in css
    coarse = re.search(r"@media \(pointer: coarse\), \(max-width: 600px\) \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "min-height: 44px" in coarse

def test_reduced_motion_turns_off_fills_and_transitions():
    css = source("app.css")
    reduced = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "transition: none" in reduced

def test_focus_ring_is_the_accent_two_pixels_offset_two():
    css = source("app.css")
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\)[^}]*outline-offset:\s*2px", css)
```

- [ ] **Step 2: Run them, fix the CSS until they pass** — `uv run pytest tests/web/test_app.py -q`.

- [ ] **Step 3: Browser check** — start the GUI from the worktree (`uv run eco web --port 8101`; the owner's own GUI uses 8100), open it in Edge (`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`), and walk the spec's Verification list: a PDF with scanned pages (`tests/fixtures` mixed PDF), a Markdown file, an EPUB, a two-file job, a failed file, a cancelled job, XTC on and off, Apply to book and return, Export and back. Take headless screenshots at 1440, 1024, 768 and 360 px of each screen (`msedge --headless --screenshot=<file> --window-size=W,H <url>`) into the scratchpad and compare each with its mockup board. Keyboard-only pass on each screen. Record what was checked and anything left in the task report.

- [ ] **Step 4: Full verification** — `uv run pytest -q && uv run ruff check && uv run ruff format --check` — Expected: all pass. Report the counts.

- [ ] **Step 5: Commit** — `git commit -m "feat: responsive and accessible page map GUI"`
