# Focus Mode Weight and Honest Style UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Focus Mode follows one fixed letter rule in EPUB and XTC with a user-chosen bold weight (600 or 700), can be switched on from Select with a "?" explanation, the Review UI says which style values change the EPUB, and Xteink X4 Pro is the default device.

**Architecture:** `PageStyle.focus_strength` becomes `focus_weight`. One Python function and one Typst `#let` carry the same letter rule and are tested against one table. The web dock counts "changes to the files" apart from "changes to the preview" for EPUB-only jobs.

**Tech Stack:** Python 3.12, FastAPI, Typst through typst-py 0.15 (`typst.query` evaluates Typst in tests), vanilla ES modules, Jinja, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-21-focus-weight-honest-ui-design.md`

## Global Constraints

- Letter rule: 1 to 3 letters → 1; 4 → 2; more than 4 → nearest whole of 40% = `(4 * n + 5) // 10` (5→2, 6→2, 7→3, 8→3, 9→4, 10→4, 12→5, 20→8). A letter is a Latin, Greek or Cyrillic letter with its combining marks.
- `focus_weight` choices exactly `(600, 700)`, default `700`. Labels "Semibold" and "Bold".
- Default device `x4-pro` everywhere (`Options`, `eco convert --device`, the Select device select).
- Old styles and jobs holding `focus_strength` still load: the key is dropped, `focus_weight` takes its default.
- All UI text in `src/eco/web/strings.py`, ASCII only; CSP: no inline style, no innerHTML; English in code, comments, commits, docs (README.id.md in Indonesian).
- Run tests with `uv run pytest tests` (bare `pytest` collects an old `out/native/` build in the main checkout).

## Review Focus

1. A saved style or `job.json` written before this change (with `focus_strength`) opens without error: Task 1 test `test_a_style_with_the_old_focus_strength_still_loads`.
2. Text weight 600 with focus weight 600: lenient load moves focus to 700; strict load (a new job) refuses with a clear message: Task 1 test `test_focus_weight_must_be_heavier_than_the_text`.
3. An uploaded font without weight 600 in XTC: the nearest heavier weight it has is used: Task 2 test `test_xtc_focus_uses_the_nearest_heavier_weight_the_font_has`.
4. An EPUB-only job where only Text size changed: Apply stays disabled, Continue stays enabled, Discard resets the preview: Task 3 test `test_an_epub_only_job_applies_only_focus_changes`.
5. Changing the Reading style on Select after ticking Focus Mode: the checkbox follows the new style: Task 4 test `test_select_focus_follows_the_reading_style`.

---

### Task 1: Style model, CLI flag

**Files:**
- Modify: `src/eco/style.py` (CHOICES, PageStyle fields, `from_json`), `src/eco/cli.py:168-177, 425-437`, `src/eco/web/app.py` only if it names `focus_strength`
- Test: `tests/test_m5_style.py`, `tests/test_saved_styles.py`, `tests/test_cli.py`, `tests/web/test_api.py:1184-1196`

**Interfaces:**
- Produces: `PageStyle.focus_weight: int = 700`; `CHOICES["focus_weight"] == (600, 700)`; no `focus_strength` field; CLI `--focus-weight {600,700}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_m5_style.py`:

```python
def test_focus_weight_replaces_strength():
    assert PageStyle().focus_weight == 700
    assert CHOICES["focus_weight"] == (600, 700)
    assert "focus_strength" not in PageStyle().to_json()
    with pytest.raises(ValueError, match="focus_weight"):
        PageStyle(focus_weight=500)

def test_a_style_with_the_old_focus_strength_still_loads():
    style = PageStyle.from_json({"focus_mode": True, "focus_strength": "high"})
    assert style.focus_mode and style.focus_weight == 700

def test_focus_weight_must_be_heavier_than_the_text():
    data = {"font": "Literata", "font_weight": 600, "focus_mode": True, "focus_weight": 600}
    with pytest.raises(ValueError, match="heavier"):
        PageStyle.from_json(data)
    findings = []
    style = PageStyle.from_json(data, lenient=True, findings=findings)
    assert style.focus_weight == 700 and style.focus_mode
    assert [f.kind for f in findings] == ["focus_weight_raised"]
```

Update `tests/test_cli.py:27-50` to pass `--focus-weight 600` instead of `--focus-strength`, and `tests/web/test_api.py:1184-1196` to send and expect `"focus_weight": 600`.

- [ ] **Step 2: Run** `uv run pytest tests/test_m5_style.py tests/test_cli.py tests/web/test_api.py -k "focus" -q` — Expected: FAIL (no `focus_weight`).

- [ ] **Step 3: Implement.** In `style.py`: replace the `focus_strength` CHOICES entry and field with `focus_weight` (600, 700; default 700). In `from_json`, drop a `"focus_strength"` key before the unknown-field check (as `margin` is handled). After the existing "no heavier weight" check, when `focus_mode` and `focus_weight <= font_weight`: strict → `ValueError("focus_weight must be heavier than font_weight")`; lenient → `focus_weight=700` with a `font_weight_raised`-style finding of kind `focus_weight_raised`, level `warning`, message `"Focus weight {old} is not heavier than the text; using 700."`. In `cli.py`: `--focus-weight` with `type=int, choices=(600, 700)`, help `"Focus Mode bold weight (default: 700, or the selected style's value)"`, wired like the old flag.

- [ ] **Step 4: Run** the Step 2 command, then `uv run pytest tests/test_saved_styles.py -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(style): Focus Mode weight replaces strength`.

### Task 2: One letter rule for EPUB and XTC

**Files:**
- Modify: `src/eco/epub/focus.py`, `src/eco/epub/optimizer.py:365-368`, `src/eco/render/md2typst.py:505-520`
- Test: `tests/epub/test_builder.py:112-185`, `tests/render/test_focus_rule.py` (create), `README.md:106`, `README.id.md` (same line)

**Interfaces:**
- Consumes: `PageStyle.focus_weight` (Task 1).
- Produces: `focus_letters(count: int) -> int` in `eco/epub/focus.py`; `focus_body(body: ET.Element, weight: int) -> None`; `FOCUS_COUNT_TYPST: str` (a `#let focus-count(n) = ...` line) and `focus_target_weight(weights: list[int], font_weight: int, focus_weight: int) -> int | None` in `eco/render/md2typst.py`.

- [ ] **Step 1: Write the failing tests** in `tests/render/test_focus_rule.py`:

```python
TABLE = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 4, 10: 4, 12: 5, 20: 8}

def test_python_rule_follows_the_table():
    assert {n: focus_letters(n) for n in TABLE} == TABLE

def test_typst_rule_follows_the_same_table(tmp_path):
    main = tmp_path / "rule.typ"
    main.write_text(FOCUS_COUNT_TYPST + f"#metadata(({', '.join(map(str, TABLE))},).map(focus-count)) <c>\n", encoding="utf-8")
    assert json.loads(typst.query(str(main), "<c>", field="value", one=True)) == list(TABLE.values())

def test_xtc_focus_uses_the_nearest_heavier_weight_the_font_has():
    assert focus_target_weight([400, 500, 600, 700], 400, 600) == 600
    assert focus_target_weight([400, 700, 900], 400, 600) == 700
    assert focus_target_weight([400, 500], 400, 700) == 500
    assert focus_target_weight([400], 400, 700) is None
```

In `tests/epub/test_builder.py`, replace the strength parametrization with weights: `@pytest.mark.parametrize("weight", [600, 700])`, assert `"HelloW"` (10 letters → 4 bold: `"Hell"`) — exact: `any(node.text == "Hell" and node.get("style") == f"font-weight:{weight}" for node in body.iter(tag("b")))`; the re-optimize test passes `focus_weight=600` the second time and still counts 2 `eco-focus` elements.

- [ ] **Step 2: Run** `uv run pytest tests/render/test_focus_rule.py tests/epub/test_builder.py -k focus -q` — Expected: FAIL (import errors / old texts).

- [ ] **Step 3: Implement.** `focus_letters(n) = 1 if n <= 3 else 2 if n == 4 else (4 * n + 5) // 10`. `focus_body` uses it and writes `style=f"font-weight:{weight}"`; the optimizer passes `self.options.style.focus_weight`. In md2typst: `FOCUS_COUNT_TYPST = "#let focus-count(n) = if n <= 3 { 1 } else if n == 4 { 2 } else { calc.quo(4 * n + 5, 10) }\n"`; the preamble emits it before the `focus` show rule, which uses `let n = focus-count(c.len())` and `text(weight: <target>)`. `focus_target_weight`: the smallest weight in `weights` that is `> font_weight` and `>= focus_weight`, else the largest weight `> font_weight`, else `None` (no focus rule emitted).

- [ ] **Step 4: Run** the Step 2 command, then `uv run pytest tests/test_m5_style.py tests/render -q` — Expected: PASS.

- [ ] **Step 5: Docs** — README.md:106 and README.id.md: `--focus-weight 600|700` (default 700) and the rule in one sentence. Commit `feat(focus): one letter rule for EPUB and XTC, chosen bold weight`.

### Task 3: Review dock: weight select, honest notes, file changes

**Files:**
- Modify: `src/eco/web/templates/index.html` (dock, settings panel), `src/eco/web/static/review.js` (STYLE_IDS, STYLE_NUMBERS, `syncReviewDock`, `changedCount`, new `fileChangeCount`, `updateApply`, `approveCurrentFile`, `renderReview`, `renderExport`), `src/eco/web/static/app.css`, `src/eco/web/strings.py`
- Test: `tests/web/test_app.py` (update `focus-strength` tests at 575-601 and 2096-2120; add new)

**Interfaces:**
- Consumes: `focus_weight` (Task 1).
- Produces: `fileChangeCount(): number` (changes that rebuild files: `size`, `focus_mode`, `focus_weight`, and every style value when the job has an XTC output); `changedCount()` stays "every difference" and drives the live preview.

- [ ] **Step 1: Write the failing tests:**

```python
def test_the_dock_offers_the_focus_weight(tmp_path):
    review = stage_markup(local(tmp_path).get("/").text, "review")
    weight = re.search(r'<select id="focus-weight">(.*?)</select>', review, re.DOTALL)
    assert re.findall(r'value="(\d+)"', weight.group(1)) == ["600", "700"]
    assert 'id="focus-weight-changed"' in review and "focus-strength" not in review
    assert (STRINGS["focus_weight_600"], STRINGS["focus_weight_700"]) == ("Semibold", "Bold")

def test_the_epub_preview_says_what_changes_the_epub(tmp_path):
    review = stage_markup(local(tmp_path).get("/").text, "review")
    assert 'id="dock-epub-note"' in review and 'id="focus-weight-note"' in review
    assert "Xteink" in STRINGS["dock_epub_note"]
    body = function_body(source("app.js"), "renderReview")
    assert "$('dock-epub-note').hidden = review.format !== 'epub'" in body

def test_an_epub_only_job_applies_only_focus_changes():
    js = source("app.js")
    count = function_body(js, "fileChangeCount")
    assert "'focus_mode'" in count and "'focus_weight'" in count and "xtc" in count
    apply = function_body(js, "updateApply")
    assert "fileChangeCount()" in apply and "changes_preview_only" in apply
    assert "fileChangeCount() > 0" in function_body(js, "approveCurrentFile")
    assert "changedCount() > 0" in function_body(js, "liveDirty")
```

Remove assertions on `focus-strength`; keep `$('focus-weight').disabled = !focus` and `$('focus-strength-field')` renamed to `focus-weight-field`.

- [ ] **Step 2: Run** `uv run pytest tests/web/test_app.py -q` — Expected: the new tests FAIL.

- [ ] **Step 3: Implement.**
  - Strings (exact): `"focus_weight_label": "Bold weight"`, `"focus_weight_600": "Semibold"`, `"focus_weight_700": "Bold"`, `"focus_weight_note": "On a reader font without semibold, both weights look bold."`, `"dock_epub_note": "Text size, spacing and margins change the XTC and this preview. On the Xteink, the EPUB follows the reader's own settings."`, `"changes_preview_only_one": "1 change in the preview only: the EPUB follows the reader's settings"`, `"changes_preview_only_other": "{n} changes in the preview only: the EPUB follows the reader's settings"`, `"panel_epub_note": "This job makes only an EPUB: these values change the preview, not the file. Focus Mode is written into the EPUB."`, `"style_value_focus": "Focus Mode {weight}"` (weight in lower case: "semibold", "bold"). Remove `focus_strength_label`, `focus_low/medium/high`, `embed_focus_label`, `embed_focus_hint`.
  - Dock: `<select id="focus-weight">` with options 600 and 700, a `focus-weight-changed` span like Focus Mode's, `<p id="focus-weight-note" class="hint">` and `<p id="dock-epub-note" class="hint">` both shown only when `review.format === 'epub'`. Settings panel: `<p id="panel-epub-note" class="muted note" hidden>` shown when the job has no XTC output.
  - `fileChangeCount()`: count `size` and the style names that differ; when the job's `options.formats` has no `xtc`/`xtch`, count only `focus_mode` and `focus_weight` among style names. `updateApply` uses it for Apply's `disabled`, the primary class, the hint and the pending status; when it is 0 but `changedCount() > 0` the status is `tn('changes_preview_only', changedCount())` and Discard stays visible. `approveCurrentFile` blocks on `fileChangeCount() > 0`. `applyChanges` unchanged.
  - Export: `style_value_focus` with `{ weight: t(`focus_weight_${style.focus_weight}`).toLowerCase() }`.

- [ ] **Step 4: Run** `uv run pytest tests/web -q` — Expected: PASS.

- [ ] **Step 5: Docs** — README.md and README.id.md Review bullet: say the dock values change the XTC and the preview, Focus Mode is written into the EPUB. Commit `feat(review): Focus weight select and honest EPUB style notes`.

### Task 4: Focus Mode on Select, X4 Pro default

**Files:**
- Modify: `src/eco/web/templates/index.html` (Select settings column, `choices` macro), `src/eco/web/static/start.js` (`chooseStyle`, `readOptions`), `src/eco/web/static/app.js` (bind the "?" button), `src/eco/web/static/app.css`, `src/eco/web/strings.py`, `src/eco/options.py:31`, `src/eco/cli.py:411`, `docs/decisions.md`, README.md, README.id.md, `DESIGN.md` (Select section)
- Test: `tests/web/test_app.py` (update `test_focus_mode_comes_from_the_reading_style_before_and_is_set_in_review`), `tests/test_options.py` or the nearest options test, tests that relied on the old default device name

**Interfaces:**
- Consumes: `focus_weight` (Task 1).
- Produces: Select elements `select-focus` (checkbox), `select-focus-help` (button, `aria-expanded`, `aria-controls="select-focus-about"`), `select-focus-about` (hidden `<p>`).

- [ ] **Step 1: Write the failing tests:**

```python
def test_select_offers_focus_mode_with_an_explanation(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    assert re.search(r'<input id="select-focus" type="checkbox"', select)
    assert re.search(r'<button id="select-focus-help" type="button"[^>]*aria-expanded="false"[^>]*aria-controls="select-focus-about"', select)
    assert re.search(r'<p id="select-focus-about"[^>]*hidden', select)
    assert "40%" in STRINGS["focus_about"] and "Review" in STRINGS["focus_about"]
    assert "focus_mode: $('select-focus').checked" in function_body(source("app.js"), "readOptions")

def test_select_focus_follows_the_reading_style():
    body = function_body(source("app.js"), "chooseStyle")
    assert "$('select-focus').checked =" in body

def test_the_default_device_is_the_x4_pro(tmp_path):
    from eco.options import Options
    assert Options().device == "x4-pro"
    assert '<option value="x4-pro" selected>' in local(tmp_path).get("/").text
```

- [ ] **Step 2: Run** `uv run pytest tests/web/test_app.py -k "select_offers or follows_the_reading or x4_pro" -q` — Expected: FAIL.

- [ ] **Step 3: Implement.** Strings: `"select_focus_label": "Focus Mode"`, `"focus_help_label": "What is Focus Mode?"` (the "?" button's accessible name), `"focus_about": "Bolds the first letters of each word so your eye finds words faster. Short words get one bold letter, longer words about 40%. It is written into the EPUB and drawn into the XTC. You can change the bold weight in Review."`. Markup under Reading style. `app.js`: the "?" toggles `select-focus-about.hidden` and `aria-expanded`. `chooseStyle` sets the checkbox from the loaded style or `builtinStyle()` once the answer is the current one. `readOptions`: `style: { ...(selectedStyle || builtinStyle()), focus_mode: $('select-focus').checked }`. Device default: `Options.device = "x4-pro"`, `--device` default `"x4-pro"`, and the `choices` macro takes a `selected` value (the device select passes `"x4-pro"`). Run the whole suite; where a test relied on the old default device, update its expected name to `x4-pro` (tests that pass `device="x4"` stay as they are).

- [ ] **Step 4: Run** `uv run pytest tests -q -p no:cacheprovider` and `uv run ruff check && uv run ruff format --check` — Expected: all pass.

- [ ] **Step 5: Docs and commit.** `docs/decisions.md` entry (2026-11-21: fixed letter rule, weights 600/700 and why not 500, honest UI, Focus Mode on Select, X4 Pro default and the new CLI output name). README(s): Select bullet mentions Focus Mode and the X4 Pro default. DESIGN.md: the Select settings list. Commit `feat(select): Focus Mode with an explanation; X4 Pro is the default device`.
