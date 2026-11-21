# Xteink EPUB Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On Xteink devices the optimizer makes publisher sizes relative, removes colors, tunes photos for e-ink, removes empty blocks and empty pages, and rebuilds a missing or broken table of contents.

**Architecture:** Pure helpers in `eco/epub/css.py`, `eco/epub/images.py`, a new `eco/epub/cleanup.py` (empty blocks, empty documents) and a new `eco/epub/toc.py` (contents check and build); `_Package` in `eco/epub/optimizer.py` calls them in the order the spec fixes and reports each as an `info` finding. `general` is untouched.

**Tech Stack:** Python 3.12, `xml.etree.ElementTree`, Pillow (`ImageOps.autocontrast`, `ImageFilter.UnsharpMask`), pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-21-epub-xteink-optimizations-design.md`

## Global Constraints

- Only when `DEVICES[options.device] is not None` (Xteink: `x4`, `x4-pro`, `x4-classic`, `x3`); `general` output must not change byte for byte in what these passes touch.
- Absolute units to px: `px` 1, `pt` 4/3, `pc` 16, `in` 96, `cm` 96/2.54, `mm` 96/25.4. `em` value = px / 16, written with at most 3 decimals, trailing zeros dropped (`0.75em`, `1.5em`).
- Keyword sizes: `xx-small` 0.6em, `x-small` 0.75em, `small` 0.89em, `medium` 1em, `large` 1.2em, `x-large` 1.5em, `xx-large` 2em, `xxx-large` 3em; `smaller`, `larger` stay.
- Line height: absolute → unitless px / 16, at least 1.2. Margin and padding: on rules whose every selector is `html` or `body`, absolute values go; elsewhere an absolute component above 32px becomes `2em`.
- Colors: `color`, `background`, `background-color`, `background-image` are removed; borders stay.
- Photos (the JPEG path): `ImageOps.autocontrast(cutoff=1)` then `ImageFilter.UnsharpMask(radius=1, percent=50, threshold=2)`; PNG and line art unchanged.
- TOC rebuilt only when missing, empty, or more than half of its entries point nowhere; from `h1`–`h3` in spine order, ids `eco-toc-N` added where missing; with no headings one entry per spine document named by `<title>` or `Section N`. EPUB 3 packages get a nav document and an NCX; EPUB 2 packages get an NCX only (a nav document is not part of EPUB 2). *(Ruling refining spec item 6: "both" applies to EPUB 3.)*
- Findings are `info`, plain English, with counts, e.g. "12 fixed sizes made relative".
- Run tests with `uv run pytest tests` (prefix PATH with `$HOME/.local/bin` in bash).

## Review Focus

1. Relative sizes (`em`, `%`, `rem`) and unitless line heights are left exactly as written: Task 1 test `test_relative_sizes_are_left_alone`.
2. White text on a dark box loses both declarations, never only one: Task 1 test `test_text_and_background_colors_go_together`.
3. An empty element that is a link target (`<p id="n1"></p>`) is kept: Task 3 test `test_an_empty_anchor_is_kept`.
4. A table of contents that works is never replaced (the messy EPUB's nav and NCX): Task 4 test `test_a_working_toc_is_kept`.
5. A nav entry that pointed at a removed empty document points at the next document: Task 3 test `test_links_to_an_empty_document_move_to_the_next`.

---

### Task 1: Publisher sizes relative, colors removed

**Files:**
- Modify: `src/eco/epub/css.py`, `src/eco/epub/optimizer.py` (`_css`, findings)
- Test: `tests/epub/test_css.py`, `tests/epub/test_optimizer.py`

**Interfaces:**
- Produces: `rewrite_css(text, retarget, xteink=False, counts: collections.Counter | None = None) -> str`; counts keys `"sizes"` and `"colors"`.

- [ ] **Step 1: Write the failing tests** (`tests/epub/test_css.py`):

```python
def test_absolute_sizes_become_relative_on_xteink():
    css = "p { font-size: 9pt; line-height: 14px } h1 { font-size: 24px; margin: 40px 0 } .k { font-size: x-small }"
    out = rewrite_css(css, keep, xteink=True)
    assert "font-size: 0.75em" in out and "font-size: 1.5em" in out and "font-size: 0.75em" in out
    assert "line-height: 1.2" in out
    assert "margin: 2em 0" in out

def test_body_margins_go_on_xteink():
    out = rewrite_css("html, body { margin: 40px; padding: 12pt; font-size: 12pt }", keep, xteink=True)
    assert "margin" not in out and "padding" not in out and "font-size: 1em" in out

def test_relative_sizes_are_left_alone():
    css = "p { font-size: 1.1em; line-height: 1.4; margin: 1em } h2 { font-size: 120%; } q { font-size: 0.9rem }"
    assert rewrite_css(css, keep, xteink=True) == css

def test_text_and_background_colors_go_together():
    counts = Counter()
    out = rewrite_css(".box { color: #fff; background-color: #222; border: 1px solid #000 }", keep, xteink=True, counts=counts)
    assert "color: #fff" not in out and "background" not in out and "border: 1px solid #000" in out
    assert counts["colors"] == 2

def test_general_keeps_sizes_and_colors():
    css = "p { font-size: 9pt; color: #777; background: #eee }"
    assert rewrite_css(css, keep, xteink=False) == css
```

And in `tests/epub/test_optimizer.py`: `test_x4_reports_relative_sizes_and_removed_colors` — a `package()` page with `<p style="font-size:10px;color:gray">t</p>` plus `css/s.css` holding `p{font-size:12pt}`; after `run(...)`, the page has no `color`, `font-size:0.625em`, and `kinds(report)` contains `"css_sizes_relative"` and `"css_colors_removed"`.

- [ ] **Step 2: Run** `uv run pytest tests/epub/test_css.py tests/epub/test_optimizer.py -k "relative or color or body_margins" -q` — Expected: FAIL.

- [ ] **Step 3: Implement.** In `css.py`, inside `_declaration` when `xteink`: drop the four color names (count `colors`); convert `font-size`, `line-height`, `margin*`, `padding*` values by the Global Constraints (count `sizes` once per declaration changed). Before the declaration pass, for each innermost block `(?P<sel>[^{}]*)\{(?P<body>[^{}]*)\}` whose comma-separated selectors are all `html` or `body` (case-insensitive, after stripping), remove margin and padding declarations whose values are absolute. `!important` is kept on a converted value. In `optimizer._css` pass one `Counter` through every call and add findings `css_sizes_relative` ("N fixed sizes made relative") and `css_colors_removed` ("N color declarations removed") when non-zero.

- [ ] **Step 4: Run** the Step 2 command, then `uv run pytest tests/epub -q` — Expected: PASS (update any existing optimizer test whose expected CSS contained an absolute size or a color on X4, and say so in the ledger).

- [ ] **Step 5: Commit** `feat(epub): relative sizes and no colors on Xteink`.

### Task 2: Photos tuned for e-ink

**Files:**
- Modify: `src/eco/options.py` (`ImageProfile`, `image_profile`), `src/eco/epub/images.py`
- Test: `tests/epub/test_images.py`

**Interfaces:**
- Produces: `ImageProfile.enhance: bool = False` (last field), `True` for Xteink.

- [ ] **Step 1: Write the failing tests:**

```python
def test_xteink_photos_get_more_contrast():
    flat = Image.new("L", (300, 300), 120)
    for x in range(300):
        for y in range(150):
            flat.putpixel((x, y), 140)
    out = Image.open(BytesIO(transform_image(_encode(flat.convert("RGB"), "JPEG", quality=95), X4).data))
    low, high = out.getextrema()
    assert low < 60 and high > 200   # stretched from 120..140

def test_general_photos_are_not_enhanced():
    assert X4.enhance and not GENERAL.enhance

def test_line_art_is_not_enhanced():
    data = _encode(_line_art(), "PNG")
    assert transform_image(data, X4).data == transform_image(data, replace(X4, enhance=False)).data
```

- [ ] **Step 2: Run** `uv run pytest tests/epub/test_images.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement.** Add `enhance` to `ImageProfile` and set it in `image_profile` for Xteink. In `transform_image`, after `thumbnail` and before saving a JPEG, when `profile.enhance`: autocontrast then unsharp mask with the constraint values. When `profile.enhance` and the output is a JPEG, the "return the source when it is final form and smaller" shortcut does not apply.

- [ ] **Step 4: Run** `uv run pytest tests/epub -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(epub): photos tuned for e-ink on Xteink`.

### Task 3: No blank screens

**Files:**
- Create: `src/eco/epub/cleanup.py`
- Modify: `src/eco/epub/optimizer.py` (`run`, a `_drop_empty` step before `_references`, NCX `content@src` follows renames in `_references`)
- Test: `tests/epub/test_cleanup.py` (create), `tests/epub/test_optimizer.py`

**Interfaces:**
- Produces: `drop_empty_blocks(body: ET.Element) -> int` (empty `p`/`div` removed plus `br` runs collapsed; returns the elements removed); `is_empty_document(body: ET.Element) -> bool` (no non-blank text after `\xa0` is treated as space, and no `img`, `svg`, `image`, `video`, `audio`, `object`).

- [ ] **Step 1: Write the failing tests** (`tests/epub/test_cleanup.py`, bodies parsed with `ET.fromstring` in the XHTML namespace):

```python
def test_empty_paragraphs_and_break_runs_go():
    body = xhtml("<p>a</p><p>&#160;</p><div style='page-break-after:always'></div><p><br/></p><p>b<br/><br/><br/>c</p>")
    assert drop_empty_blocks(body) == 5   # 3 empty blocks + 2 extra br
    assert texts(body) == ["a", "b", "c"] and len(body.findall(".//{*}br")) == 1

def test_an_empty_anchor_is_kept():
    body = xhtml("<p id='n1'></p><p>t</p>")
    assert drop_empty_blocks(body) == 0

def test_tails_survive():
    body = xhtml("<div>x<p> </p>tail</div>")
    drop_empty_blocks(body)
    assert "".join(body.itertext()) == "xtail"

def test_empty_document_detection():
    assert is_empty_document(xhtml("<p>&#160;</p><div></div>"))
    assert not is_empty_document(xhtml("<p><img src='a.jpg' alt=''/></p>"))
    assert not is_empty_document(xhtml("<p>word</p>"))
```

In `tests/epub/test_optimizer.py`: `test_links_to_an_empty_document_move_to_the_next` — `package()` with pages `a` (`<p><a href="blank.xhtml">go</a></p>`), `blank` (`<p>&#160;</p>`), `c` (`<p>c</p>`); after `run(...)` on X4: `text/blank.xhtml` is gone from zip, manifest and spine, the link in `a` points at `c.xhtml`, and `kinds(report)` contains `"empty_removed"`. And `test_general_keeps_empty_pages` — the same package with `GENERAL` keeps `blank.xhtml`.

- [ ] **Step 2: Run** `uv run pytest tests/epub/test_cleanup.py tests/epub/test_optimizer.py -k "empty or tails" -q` — Expected: FAIL.

- [ ] **Step 3: Implement.** `cleanup.py` removes an element by moving its tail to the previous sibling's tail or the parent's text. `_drop_empty` (Xteink only, runs after `_fonts`, before `_references`): calls `drop_empty_blocks` on every page body; then for each spine document (not the nav document) whose body `is_empty_document`, removes the file, its manifest item and its doc **without** adding it to `self.removed`, and sets `self.renamed[path]` to the next spine document that remains (the previous one when it is last), so `_retarget` moves links. `_references` also rewrites `content@src` in the NCX through `_retarget`. One finding `empty_removed`: "N empty paragraphs and M empty pages removed" (omit a zero part).

- [ ] **Step 4: Run** `uv run pytest tests/epub -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(epub): remove empty blocks and empty pages on Xteink`.

### Task 4: A working table of contents

**Files:**
- Create: `src/eco/epub/toc.py`
- Modify: `src/eco/epub/optimizer.py` (`run`: `_contents` after `_split_chapters`, before `_tidy`), README.md, README.id.md, docs/decisions.md
- Test: `tests/epub/test_toc.py` (create), `tests/epub/test_optimizer.py`

**Interfaces:**
- Produces: `TocEntry(level: int, label: str, path: str, anchor: str)` dataclass; `headings(pages: list[tuple[str, ET.Element]]) -> list[TocEntry]` (adds `eco-toc-N` ids where missing; falls back to one entry per page with its title or `Section N`); `broken_share(targets: list[str], exists: Callable[[str], bool]) -> float`; `nav_body(entries, base: str) -> ET.Element` and `ncx_map(entries, base: str) -> ET.Element` (nested by level).

- [ ] **Step 1: Write the failing tests** (`tests/epub/test_toc.py`):

```python
def test_headings_in_order_with_ids():
    pages = [("t/a.xhtml", xhtml("<h1>One</h1><p>x</p><h2 id='s'>Sub</h2>")), ("t/b.xhtml", xhtml("<h1>Two</h1>"))]
    entries = headings(pages)
    assert [(e.level, e.label, e.path, e.anchor) for e in entries] == [
        (1, "One", "t/a.xhtml", "eco-toc-1"), (2, "Sub", "t/a.xhtml", "s"), (1, "Two", "t/b.xhtml", "eco-toc-2")]

def test_no_headings_gives_one_entry_per_page():
    pages = [("t/a.xhtml", xhtml("<p>x</p>", title="Start")), ("t/b.xhtml", xhtml("<p>y</p>", title=""))]
    assert [e.label for e in headings(pages)] == ["Start", "Section 2"]

def test_ncx_nests_by_level():
    entries = [TocEntry(1, "One", "t/a.xhtml", "a"), TocEntry(2, "Sub", "t/a.xhtml", "s")]
    nav_map = ncx_map(entries, "")
    outer = nav_map.find("{*}navPoint")
    assert outer.find("{*}navLabel/{*}text").text == "One"
    assert outer.find("{*}navPoint/{*}navLabel/{*}text").text == "Sub"

def test_broken_share():
    assert broken_share(["a", "b", "c"], {"a"}.__contains__) == 2 / 3
```

In `tests/epub/test_optimizer.py`: `test_a_missing_toc_is_rebuilt_from_headings` — `package()` (its NCX navMap is empty) with pages holding `<h1>One</h1>` and `<h1>Two</h1>`; after X4 `run`, the NCX lists "One", "Two" in that order, a nav document with `properties="nav"` exists (the package is EPUB 3) and every entry resolves (`check_package`); finding `"toc_rebuilt"`. `test_a_working_toc_is_kept` — `messy_epub` on X4: nav and NCX labels are the same as in the input, and no `"toc_rebuilt"`. `test_general_never_rebuilds_the_toc`.

- [ ] **Step 2: Run** `uv run pytest tests/epub/test_toc.py tests/epub/test_optimizer.py -k "toc" -q` — Expected: FAIL.

- [ ] **Step 3: Implement** `toc.py` and `_contents`: read entries from the nav document (`nav[epub:type=toc]` links) and the NCX (`content@src`); rebuild when both are missing, both have no entries, or `broken_share` of all entries is above 0.5 (a target is broken when its file is gone or its fragment id is not in that page). Fill an existing NCX's `navMap` (else add `toc.ncx`, a manifest item and `spine@toc`); for EPUB 3 replace the `toc` nav of an existing nav document (else add `nav.xhtml` with `properties="nav"`, not in the spine). Finding `toc_rebuilt`: "Table of contents rebuilt from N headings".

- [ ] **Step 4: Run** `uv run pytest tests -q -p no:cacheprovider` and `uv run ruff check && uv run ruff format --check` — Expected: all pass. Existing X4 optimizer tests built with `package()` now gain a rebuilt TOC; update only expectations that list the manifest or zip names exactly, and ledger each.

- [ ] **Step 5: Docs and commit.** README.md and README.id.md: one paragraph in the optimizer section on what Xteink output now does (relative sizes, no colors, photos tuned, empty blocks and pages removed, a rebuilt contents when missing). docs/decisions.md: 2026-11-21 entry with the five changes and the EPUB 2 / EPUB 3 contents rule. Commit `feat(epub): rebuild a missing or broken table of contents on Xteink`.
