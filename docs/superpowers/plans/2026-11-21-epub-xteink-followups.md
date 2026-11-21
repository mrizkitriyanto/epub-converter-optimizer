# Xteink EPUB Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Judge the nav and NCX each on its own, reach more page boxes and the font shorthand, and keep enhanced photos no bigger than plain ones.

**Architecture:** `eco/epub/toc.py` gains readers that turn a nav or NCX into `TocEntry` lists; `_contents` writes whichever file is broken from the working one. `rewrite_css` gains `page_classes` and `page_box` parameters; the optimizer collects `<body>` classes. `transform_image` steps the JPEG quality down for enhanced photos.

**Tech Stack:** Python 3.12, ElementTree, Pillow, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-epub-xteink-followups-design.md`

## Global Constraints
- Xteink only; `general` unchanged. Quality step 2, at most 15 below the profile. Every regex starts only at a boundary (linear time).

## Review Focus
1. A working nav with no NCX gets an NCX with the nav's labels: Task 1 `test_a_working_nav_fills_a_missing_ncx`.
2. `small-caps` in a font shorthand is not taken for the size keyword `small`: Task 2 `test_font_shorthand_sizes_become_relative`.
3. A class that is on `<body>` in one page and on paragraphs elsewhere: only margin and padding go, never text: Task 2 `test_a_body_class_rule_loses_margins_only`.
4. An enhanced photo is never larger than the plain encoding unless the floor is reached: Task 3 `test_an_enhanced_photo_is_no_bigger_than_a_plain_one`.
5. Both files broken still build from headings (existing tests).

---

### Task 1: Each contents file on its own
**Files:** `src/eco/epub/toc.py`, `src/eco/epub/optimizer.py` (`_contents`, `_toc_targets`); tests `tests/epub/test_toc.py`, `tests/epub/test_optimizer.py`.
**Produces:** `entries_from_nav(nav: ET.Element, owner: str) -> list[TocEntry]`, `entries_from_ncx(nav_map: ET.Element, owner: str) -> list[TocEntry]` (levels from nesting, `path` resolved against `owner`, `anchor` from the fragment).
- [ ] Tests: the two readers round-trip `nav_body`/`ncx_map` output; `test_a_working_nav_fills_a_missing_ncx` (EPUB 3 with a nav of "One","Two" and no NCX → NCX labels "One","Two", nav unchanged, finding `toc_rebuilt` names the NCX); `test_a_working_ncx_fills_a_broken_nav` (nav all broken, NCX working → nav labels from the NCX).
- [ ] Run, see them fail; implement: judge each file, take entries from the working one (or headings when both are broken), write only the broken ones; finding "Table of contents written: NCX from the nav" (or "nav from the NCX", or "both from N headings").
- [ ] `uv run pytest tests/epub -q` green; commit `feat(epub): fill a missing nav or NCX from the one that works`.

### Task 2: More page boxes and the font shorthand
**Files:** `src/eco/epub/css.py`, `src/eco/epub/optimizer.py` (`_css` passes body classes, `page_box=True` for `<body style>`); tests `tests/epub/test_css.py`, `tests/epub/test_optimizer.py`.
**Produces:** `rewrite_css(text, retarget, xteink=False, counts=None, page_classes=frozenset(), page_box=False) -> str`.
- [ ] Tests: `test_body_with_a_class_and_page_rules_lose_margins` (`body.calibre{margin:40px}`, `@page{margin:1in}`, `@page :first{margin:2cm}` lose margins); `test_a_body_class_rule_loses_margins_only` (`.calibre{margin:5pt;font-size:12pt}` with `page_classes={"calibre"}` → no margin, `font-size: 1em`); `test_font_shorthand_sizes_become_relative` (`font: italic 9pt/14px serif` → `font: italic 0.75em/1.2 serif`; `font: small-caps 12px serif` → `font: small-caps 0.75em serif`); `test_a_body_style_attribute_loses_margins` (optimizer: `<body style="margin:40px">` → no margin); add `"p{font:" + "1"*16000 + "}"` to the linear-time inputs.
- [ ] Run, see them fail; implement.
- [ ] Green; commit `feat(epub): more page boxes and the font shorthand on Xteink`.

### Task 3: Enhanced photos are no bigger
**Files:** `src/eco/epub/images.py`; tests `tests/epub/test_images.py`; README.md, README.id.md, docs/decisions.md.
- [ ] Test `test_an_enhanced_photo_is_no_bigger_than_a_plain_one`: for several noise photos and each Xteink size, `len(enhanced) <= len(plain)` or the quality floor was used (assert via a `quality` field on the result or by re-encoding at the floor).
- [ ] Run, see it fail; implement the step-down loop (plain encode once, then enhanced at q, q-2, … ≥ q-15).
- [ ] Docs: README paragraph and decisions entry; full suite, ruff; commit `feat(epub): enhanced photos are no bigger than plain ones`.
