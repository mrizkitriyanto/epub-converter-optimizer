# M5: Reading style (design)

- Date: 2026-11-18. Status: APPROVED by the owner on 2026-11-18 ("setuju"). A builder check was done,
  `.superpowers/m5-builder-check.md`.
- Origin: brainstorm with the owner in the M1-M4 session. Running notes: `.superpowers/m5-brainstorm-notes.md`.
- Builds on M3 (branch `m3-xtc`):
  - `PageStyle` in `src/eco/style.py`;
  - the Typst renderer `src/eco/render/md2typst.py`;
  - the M3 plan's Task 6 (CLI `--style`, `--font`) and Task 7 (page style panel, fonts API, live preview);
  - spec §8.18 (`docs/superpowers/specs/2026-11-16-epub-converter-optimizer-design.md`, Indonesian).
- M5 starts after M4 (Docker and release).
- The implementation plan for M5 is written when M5 starts, not now. This is the controller's
  call, from the builder check. M5 builds on M3 Tasks 6-7 (`--style`, `--font`, the fonts API, the
  page style panel, the XTC stage), which do not exist yet. The plan then:
  - names the real interfaces;
  - begins with a task that records M3 golden renders, the baseline for "defaults reproduce M3".
- M3 still builds its per-job font upload as planned; M5 moves the panel's upload to the library.

## Why

The owner wants to read XTC books on the Xteink X4 in their own style, set once and reused for every
book: their own fonts, a reading aid that bolds the start of words, and control over alignment and
spacing. The owner did not state a reason beyond the features. The working assumption is reading
comfort on the X4.

## What M5 adds

| # | Feature | Kind |
|---|---|---|
| 1 | Font library: upload fonts once, use them for every book (GUI and CLI) | new |
| 2 | Focus Mode: bold the first part of each word in body text, XTC only | new |
| 3 | Focus Mode strength: Low / Medium / High | new |
| 4 | Center alignment: a third value next to justify and left | extends `align` |
| 5 | Margins split into left/right and top/bottom | replaces `margin` |
| 6 | Paragraph spacing | new |
| 7 | First-line paragraph indent | new |
| 8 | Saved styles and a default style for new jobs | new |
| 9 | A warning when the chosen font lacks characters the book uses | new |

Font weight, font size, line spacing (`line_height`) and hyphenation already exist in M3 and are
unchanged, except that Focus Mode depends on the font's weights (below).

## Goals

- Every setting above changes the XTC output as expected and has its own test (spec §9 item 15).
- Preview and file stay identical for XTC (spec §8.18 "identical").
- Defaults reproduce today's output exactly: an M3 style renders the same pages in M5.
- A style set once (fonts included) is reusable for every book from the GUI and the CLI. The
  "defaults reproduce" goal is measured with no saved default style.

## Non-goals

- Changing the EPUB file. Focus Mode never touches EPUB, fonts are never embedded in EPUB (X4 rule,
  M1 AC7), and the other new settings only reach the EPUB live preview as the existing simulation
  (M3 ruling M3-R3).
- Letter spacing, word spacing, heading styles, and per-element font sizes. The owner may revisit
  them after using M5 on the device.
- Variable-font axes, font collections (`.ttc`), and downloading fonts from the internet. Fonts
  come only from files the user uploads; conversion stays offline.
- Syncing the library or styles between machines.

## Anti-goals (a failure even if it works)

- Focus Mode changes the book's text. The characters must stay the same: the PDF text of a page
  with and without Focus Mode is identical; only weights differ.
- A character is drawn in another font without the user being told.
- Deleting a library font breaks a job, a saved style or the default style.
- The XTC live preview and the produced file differ.
- The page style panel becomes too slow to use: spec §9 item 14 (<= 1 s for a 30-page chapter on
  an M3 Mac) holds with Focus Mode on.

## Constraints

- Spec §5: no content changed or lost without a finding.
- §8.18: XTC preview equals the file.
- §9 items 14-15.
- Fonts: `.ttf`/`.otf` only, validated before use (M3 Review Focus 3: `Not a usable font file`).
- No network during conversion (AGENTS.md).
- UI text in English, following DESIGN.md and antislop.
- Every value that reaches Typst source is validated or escaped (M3 ruling M3-R9).
- The GUI listens on 127.0.0.1 only (M2).

## Approaches considered

**Focus Mode: where the bolding happens.**

1. **eco writes the bold spans.** md2typst splits each word of body text and emits
   `#text(weight: W)[Foc]us`.
   - For: full control of scope (eco knows each block's kind), letter counting in Python, and
     tests on the Typst source.
   - Against: a longer source per page, and more renderer code.
2. **One Typst rule (chosen by the owner).** md2typst writes the text unchanged and the preamble
   holds a scoped regex show rule that bolds the first part of each word at layout time.
   - For: little code, and the book text in the source stays as it is.
   - Against: the rule needs explicit exclusions; Typst string lengths are UTF-8 bytes, so the rule
     must work on grapheme clusters; it can be tested only by rendering.

Both add per-word work at layout, so speed must be measured either way. The owner chose 2 after
seeing both written out.

**Extra fonts: where they live.**

1. Per job, as M3 builds: uploaded in a job and deleted with it.
2. **A library in the data folder (chosen by the owner)**: uploaded once and offered for every
   book. M3's per-job upload still ships in M3. M5 moves the panel's upload to the library.

## Design

### 1. PageStyle changes

| Field | Change | Default | Allowed | Typst |
|---|---|---|---|---|
| `align` | gains `center` | `justify` | `justify`, `left`, `center` | center: `par(justify: false)` plus centered body paragraphs |
| `margin_x` | new, replaces `margin` | 16 | 0-80 px | page margin left and right |
| `margin_y` | new, replaces `margin` | 16 | 0-80 px | page margin top and bottom (the bar area is added as today) |
| `paragraph_spacing` | new | 120 | 0-300, % of font size | `par(spacing: <v/100>em)`; 120 equals Typst's default 1.2em, so today's output is unchanged |
| `first_line_indent` | new | 0 | 0-400, % of font size | `par(first-line-indent: <v/100>em)` |
| `focus_mode` | new | `False` | bool | the Focus Mode rule |
| `focus_strength` | new | `medium` | `low`, `medium`, `high` | ratio 0.3, 0.5, 0.7 |

- **Strict input, lenient stored state.** This is the controller's call, from the builder check.
  - What the user gives right now is checked strictly, and an unknown font or an impossible Focus
    Mode is an error. That covers:
    - CLI `--font NAME` (an error listing the available families);
    - `--style FILE`;
    - the panel's live preview and Apply (HTTP 422);
    - a font upload.
  - What was stored earlier loads and degrades with a finding:
    - a job's `job.json`;
    - a saved style, also when read by `--style NAME`, in which case the CLI prints the finding;
    - the default style.
    A missing family falls back as in section 3, and an impossible Focus Mode renders without it.
  - `PageStyle.from_json` therefore gets a strict and a lenient mode. The lenient mode returns the
    style plus the findings to record.
- **Migration.** A style or `job.json` that holds `margin: N` (M3) loads as `margin_x = margin_y = N`,
  the same way M3 ruling M3-R8 upgraded `font_size`. `to_json` writes only the new keys. Nothing
  else is migrated.
- **Margin geometry.** "Top" and "bottom" are in the reader's frame. The renderer already lays out
  the page turned for 90/270 and turns the image back, so margins follow the reading orientation.
  The progress bar uses `margin_y` where it now uses `margin` for its vertical origin, and
  `margin_x` for its horizontal origin.
- **Indent.** Typst does not indent a paragraph that does not follow another paragraph, so the
  first paragraph after a heading stays flush (book convention).

### 2. Focus Mode rendering

- **Scope.** The rule applies to body text: paragraphs, list items and block quotes. It does not
  apply to headings, code (inline and blocks), link text, table cells, captions, or the progress bar.
- **A word** is a run of Latin, Greek or Cyrillic letters with their combining marks, for example
  `(?:[\p{Latin}\p{Greek}\p{Cyrillic}]\p{M}*)+`. Digits and punctuation are never bolded, and an
  apostrophe splits a word.
  - Other scripts stay as they are. Scripts without spaces (CJK, Thai) would turn whole runs
    bold, and in joined scripts (Arabic) a weight change inside a word breaks the joining.
  - This is the controller's call, from the builder check.
- **How much of a word.** Count grapheme clusters (`str.clusters()`), never bytes.
  - With `n = len`: a 1-letter word is bold entirely.
  - Otherwise, `ceil(n x ratio)` letters are bold, at least 1 and at most `n - 1`, so a word never
    turns fully bold.
- **The bold weight.** Use the lightest available weight of the chosen font that is at least
  `font_weight + 300`. If there is none, use the heaviest available weight above `font_weight`.
  - If there is none at all, Focus Mode is unavailable for that font and weight:
    - the panel disables the switch with "This font has no heavier weight";
    - `--style` with `focus_mode: true` on such a font is an error naming the font;
    - a saved or default style that meets this (for example after a font was deleted) renders
      without Focus Mode and records a finding.
- **Text unchanged.** The PDF text of a rendered page is the same with Focus Mode on and off. The
  M3 exactness tests (M3-R10) must pass with Focus Mode on.
- **Hyphenation and justification still work.** Test: a paragraph that hyphenates with Focus Mode
  off still hyphenates with it on, and no line overflows the text area.
- **Speed.** This is the controller's call, from the builder check. Spec §9 item 14 (<= 1 s on an
  M3 Mac) cannot be checked on the owner's laptop, which already takes about 1.5-2 s warm for a
  25-30-page chapter without Focus Mode (M3 Task 2 measurements). The check that can run here:
  - on the same machine, a warm `render_chapter` of a 30-page text chapter takes at most 1.5 times
    as long with Focus Mode on as with it off;
  - the median of 5 alternating rounds is reported with the hardware;
  - the absolute target stays with the device and Mac check, as for agent decision Q-6.
- **If the Typst rule fails.** The owner decided: the builder may switch to approach 1 (eco writes
  the bold spans) without asking, and records why in docs/decisions.md and the ledger. "Fails"
  means it misses the speed check, or fails the same-text, hyphenation or justification tests.
  Everything else in this section holds for approach 1 too.
- **EPUB.** The switch shows only when an XTC format is selected. EPUB previews never apply it.

### 3. Font library

- **Storage.** `<data>/fonts/`, where `<data>` is `resolve_data_dir()` (the folder that holds
  `models/`). In Docker (M4), the data volume keeps the library.
- **Upload.** One or more `.ttf`/`.otf` files at once.
  - Each file is checked (Typst can read a family from it), or it gets HTTP 400 / CLI error
    `Not a usable font file` naming the file.
  - A file may not exceed 30 MB.
  - Stored names are made by eco, never taken from the client's path.
  - Identical bytes already in the library: nothing happens.
  - The same family, weight and style as a stored file: the new file replaces it, and the response
    says so.
  - A family named like a bundled family or "Libertinus Serif" is refused with
    `A built-in font already has this name`.
- **Listing.** Families with their weights and styles, and whether Focus Mode is available at each
  body weight (some weight at least 300 heavier, or any heavier weight).
- **Delete.** A whole family at once.
  - Jobs, saved styles and the default style that name it keep the name.
  - At their next render they fall back to Literata at the nearest available weight, with a
    finding `font_missing` that names the family. The panel shows the same note.
- **Font search order** for rendering: bundled, then the library, then the job's own `fonts/`
  (M3 uploads, kept working).
- **The job font upload of M3** (`POST /api/jobs/{id}/fonts`) is removed from the UI; the panel's
  "Upload font..." adds to the library. Whether the endpoint itself stays is the builder's call:
  fonts already in a job folder keep rendering either way.
- **API:**
  - `GET /api/fonts`: bundled, library, and with `?job=` that job's fonts;
  - `POST /api/fonts`: multipart, several files;
  - `DELETE /api/fonts/{family}`.
- **CLI:**
  - `eco fonts list`;
  - `eco fonts add FILE...`;
  - `eco fonts remove FAMILY`;
  - `--font NAME` also finds library families, and `--font PATH` (M3) still works.

### 4. Missing characters

- **Check.** When a book renders to XTC, compare the characters of its body text with the chosen
  font's character map (fontTools, already a dependency). Leave out white space and control
  characters.
- **Finding.** If any are missing, record `font_fallback` with the count and up to 20 of the
  characters. Typst keeps its fallback on, so the characters still show, in another available font.
- **Live preview.** The panel shows the same count for the chapter on screen.
- **Bundled fonts.** The check applies to them too.

### 5. Saved styles and the default style

- **Storage.** `<data>/styles/<name>.json`, each holding `PageStyle.to_json()`.
  - A name is 1-40 characters: letters, digits, space, `-` and `_`. It is unique, ignoring case.
  - The default is recorded in `<data>/settings.json` as `{"default_style": "<name>"}`.
- **GUI.** In the page style panel:
  - "Save style...": name it, and overwrite after a confirmation;
  - a "Style" select to load one;
  - "Make default";
  - "Delete".
  New jobs start with the default style, or the built-in defaults when there is none.
- **The CLI and the default style.** The owner decided: yes.
  - `eco convert` without `--style` uses the saved default style, or the built-in defaults when
    none is set, and prints the style it used, for example `Style: Night reading (default)`.
  - `--style` replaces the style, and `--font` and `--font-size` apply on top of whichever style is
    in use.
  - Docker uses the default in its data volume the same way.
  - CLI tests use a fresh data folder, as they already do.
- **CLI.** `--style VALUE` reads a file when VALUE is a path to an existing file. Otherwise it reads
  the saved style of that name, and otherwise it is an error listing the saved names.
  `eco styles list` shows them, with the default marked.
- **Loading.** Every load goes through `PageStyle.from_json`, so validation and migration apply. A
  file that fails is listed as broken with its error and is not offered.
- **Fonts.** A style that names a font no longer available loads, and its renders fall back as in
  section 3.

### 6. GUI

- **The page style panel (M3 Task 7)** gains:
  - Center in Alignment;
  - Margin left/right and Margin top/bottom (two controls in place of Margin);
  - Paragraph spacing and First-line indent in the Text group;
  - the Focus Mode switch and its strength in the Text group, shown only for XTC;
  - the Style select with Save, Make default and Delete.
- **A Settings view** with a Fonts section: upload, the family list (weights, Focus Mode yes/no)
  and Delete. Where Settings sits in the M2 layout is the builder's call within DESIGN.md.
- **Every new control** feeds the debounced live preview like the existing ones.

### 7. Tests and acceptance

- Each new setting has a test that it changes the XTC output, and that its default reproduces an
  M3 render byte for byte.
- Focus Mode:
  - the PDF text equals the text with Focus Mode off;
  - bold ink appears at word starts in body text and not in headings, code or links;
  - accented words split by letters (`café`, `über`, Indonesian text);
  - the weight rule;
  - unavailable fonts;
  - the speed measurement.
- Font library:
  - not a font gives 400 with the message;
  - duplicates and replacement;
  - a built-in name is refused;
  - delete followed by fallback with the finding;
  - the CLI `fonts` commands;
  - a file over the size limit.
- Saved styles:
  - save, load, default for a new job, delete;
  - `--style NAME` against a path;
  - a broken file is listed as broken;
  - migration of `margin`.
- Missing characters: a font without `é` gives the finding with the count.
- Manual checks are added to the GUI checklist (`docs/qa/m2-gui-checklist.md`, an "M5" section),
  including Focus Mode read on the device.

### 8. Spec and docs

- The spec gains an M5 entry in its milestone list and the new rows in the §8.18 table. The spec
  is Indonesian.
- docs/decisions.md gets dated entries for:
  - the Focus Mode name and the reason for it (trademark);
  - the choice of the Typst rule;
  - the library location;
  - the `margin` migration.

## Decided by the owner

- The Focus Mode name, in place of "Bionic Reading", which is a registered trademark.
- A font library, not only per-job uploads.
- Focus Mode built as a Typst rule.
- Separate left/right and top/bottom margins, plus paragraph spacing.
- Focus Mode uses a heavier weight than the body.
- First-line indent.
- Saved and default styles, Focus Mode strength, and the missing-character warning (the
  controller's three suggestions, accepted).
- If the Typst rule fails, switch to approach 1 without asking.
- The CLI uses the default style.

## The controller's calls (check these)

- Focus Mode:
  - XTC only, default off;
  - scope: body text, without headings, code, links, tables and captions;
  - the word definition;
  - strength ratios 0.3, 0.5 and 0.7;
  - the weight rule (+300, else the heaviest heavier weight).
- Center alignment ships in M5, not M3.
- Units: paragraph spacing and indent in % of the font size; paragraph spacing default 120 to keep
  today's output.
- `margin` is migrated to `margin_x` and `margin_y`.
- The font library:
  - 30 MB per font file;
  - identical files ignored and same-face files replaced;
  - built-in names refused;
  - a deleted font falls back to Literata with a finding.
- Fonts are searched in the order bundled, library, job folder.
- From the builder check:
  - the speed check: at most 1.5 times slower, warm, median of 5 alternating rounds;
  - strict checks for input given now, and a lenient load with a finding for stored state;
  - Focus Mode for Latin, Greek and Cyrillic only;
  - the M5 plan is written when M5 starts, with an M3 golden-render baseline first;
  - M3 keeps its per-job font upload.
- Style names follow the rule above, the default lives in `settings.json`, and `--style` resolves a
  path first, then a name.

## Left to the builder

- The library's file naming and any index file.
- Whether M3's job font endpoint stays.
- The Typst code of the Focus Mode rule and its exclusions, within the requirements above.
- Where Settings sits in the GUI, and the controls' exact layout (DESIGN.md).
- How the missing-character check gets the book's characters (book.md, or the blocks).
