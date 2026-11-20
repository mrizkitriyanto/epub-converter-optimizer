# End-to-end GUI redesign: the page map

Date: 2026-11-20

Supersedes `2026-11-20-guided-workspace-redesign.md` for the visual and interaction design of the
web GUI. That earlier spec's capability inventory still holds: nothing the GUI can do today is
removed.

Mockups (approved by the owner on 2026-11-20): the Design canvas
https://claude.ai/artifact/XQEfNf5wvU7w3MiPxhp8LZ, second row "End to end, direction C"
(boards `1 · Select`, `2 · Convert`, `3 · Review`, `4 · Export`). The first row holds the three
directions that were compared. The canvas is private to the owner. The values in this document
override the mockup wherever the two differ.

## Intent

The owner wants the eco web GUI to feel **elegant, minimal and effective**, and to be **clear
and transparent about what the conversion is doing**. A user should always be able to answer three
questions at a glance: where am I in the process, what is eco doing right now, and where in my
book did something need attention.

The central idea is the **page map**: the book drawn as one small square per source page. It
appears on every screen and changes role with the step:

| Step | What the page map shows |
|---|---|
| Select | Which pages are digital text and which are scanned (will use OCR) |
| Convert | Which pages are done, which page is being worked on, which are waiting, which have findings |
| Review | A thin strip used to move through the book; findings and the current page are marked |
| Export | Not shown; the summary line names the page and finding counts |

## Goals

- Four steps, always visible in the header: Select, Convert, Review, Export.
- One high-emphasis (blue) button per screen.
- Progress shown three ways at once, each in text as well as graphics: overall percent and time
  left, the six pipeline stages as a segmented bar, and the page map.
- Findings visible while they happen, located on the page map, and followed into Review.
- Review is required before Export (owner decision, 2026-11-20).
- Style changes in Review show live in the preview, and the screen says plainly when a change is
  in the preview but not yet in the files.
- Multi-file conversions: a queue the user can see, and a converted file can be reviewed while the
  next one converts.

## Non-goals

- Changing conversion algorithms, output formats or preview rendering.
- Breaking changes to persistence formats. Additive fields in events and `job.json` are allowed
  (see Backend changes); old jobs without them still load and show what they can.
- Accounts, cloud features, analytics, or any network access from the page.
- A frontend framework, a build step, or a component or icon library.
- Redesigning the CLI.
- Dark theme (DESIGN.md keeps "light theme only").

## Anti-goals

These would make the redesign a failure even if every feature works:

- A dashboard of cards and numbers before the user has started.
- Any state told only by color. Every status has a word next to it.
- Progress that lies: a bar that jumps backwards, a percent that sits at 99 %, a "done" stage that
  is still running.
- Hiding a failure or a warning so the screen looks calmer.
- Rebuilding the output files on every slider movement.
- Loading anything from the internet, fonts included.

## Approaches considered

Three directions were mocked up for the Convert screen (canvas row 1):

- **A · Quiet column.** One centered column with percent, a thin bar, a list of stages and
  findings collapsed. Calmest and cheapest. It tells the user *how much* is done, not *where* in
  the book problems are.
- **B · Pipeline rail.** A permanent left rail with the whole journey and sub-stages, plus figures,
  a timestamped activity log and findings. The most text-transparent option, but the densest; it
  reads as a dashboard, and the rail takes the width that Review's side-by-side comparison needs.
- **C · Page map.** The book as a grid of page squares filling as pages are read, findings marked
  on the map, and a segmented stage bar above it. It shows the process without adding text, and it
  links straight into Review (a page square opens that page).

**The owner chose C** and asked for it end to end. The rail of B and the stage list of A are not
carried over; the segmented stage bar of C replaces both.

## Visual system

DESIGN.md is rewritten with these values; the current tokens are replaced.

### Tokens

| Token | Value | Use |
|---|---|---|
| Background | `#FAFAF9` | page |
| Panel | `#FFFFFF` | panels, header, inputs |
| Border | `#E4E4E7` | panel borders, row dividers |
| Control border | `#D4D4D8` | inputs, secondary buttons |
| Text | `#18181B` | body text |
| Muted | `#52525B` | secondary text |
| Subtle | `#71717A` | hints, waiting states (4.8:1 on white) |
| Accent | `#1D4ED8` | primary button, current page, in-progress stage, links |
| Success | `#15803D` | "Done" text and marks |
| Warning text | `#B45309` | finding labels |
| Warning mark | `#F59E0B` | finding squares on the page map (graphic only, never text) |
| Error | `#B91C1C` | failure text, destructive action |
| Page done | `#3F3F46` | page map |
| Page waiting | `#E4E4E7` | page map |
| Page scanned | `#6D28D9` | Select page map |
| Page digital | `#D4D4D8` | Select page map, Review strip |
| Device bezel | `#262626` | device preview |
| E-ink screen | `#E9E9E4` | device preview |

All text pairs meet 4.5:1. The four page map states differ in lightness, not only in hue.

### Type

- Font: **Inter**, variable woff2, bundled under `src/eco/web/static/fonts/` with its OFL licence,
  loaded with `@font-face` from the app itself. Fallback stack:
  `"Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif`. (Builder call made by the
  designer: the mockup loaded Inter from Google Fonts; the product must not.)
- Base 14 px, line height 1.5. Screen titles 26–28 px weight 600, letter spacing -0.02em. Large
  figures (percent) 36–44 px weight 500. Labels and hints 12–13 px.
- `font-variant-numeric: tabular-nums` on every changing number (percent, pages, times).

### Shape and spacing

- Radii: controls 8 px, panels 10 px, page squares 2 px, segmented controls 6 px.
- Structure comes from borders and spacing. No shadows, gradients or colored left borders.
- Touch targets at least 44×44 px.
- Icons are inline stroke SVG (1.8–2 px stroke), `aria-hidden` when next to text.

## Shared shell

- Header: brand "eco" left; step indicator center (Select, Convert, Review, Export; the current
  step in text color with an underline, the others subtle); "Runs on this computer" right.
- The step indicator is a `<nav>` with `aria-current="step"` on the current step. Completed steps
  are links only where going back is valid: Select is always reachable (it starts a new
  conversion; a running job keeps running and stays in Recent conversions); Review is reachable
  from Export. Other steps are plain text.
- Content width: 1120 px max for Select and Convert, 1400 px for Review, 640 px for Export.

## Screen 1 · Select

Layout: title "Convert a book" and one line of intro. Two columns on wide screens (book left,
settings right), one column below 900 px. Recent conversions below.

**Book column**

- Drop area: label wrapping a hidden file input. Text: "Drop files here or choose files", hint
  "PDF, Markdown or EPUB, up to 500 MB" (the limit comes from the server setting).
- One row per chosen file: name, then a meta line (pages, size, kind, estimate), and a remove
  button with an accessible name naming the file. The meta line reuses today's strings
  (`kind_partly`, `estimate_about`, and so on).
- **PDF rows show a page map**: 10 px squares, digital pages in Page digital, scanned pages in
  Page scanned, with a legend ("Digital text", "Scanned, read with OCR"). When OCR is Off, the
  legend says "Scanned, no OCR". The map has `role="img"` and an `aria-label` that states the
  counts ("412 pages, 38 scanned"). Markdown and EPUB rows have no map.
- While a PDF is being inspected, the row shows "Reading…" and no map.

**Settings column**

- Reading device (select), Output (EPUB and XTC as two checkbox tiles, each with a one-line
  description), Reading style (select of saved styles, the default style preselected, hint "You can
  fine-tune it in Review."), File size (three-way segmented radio: Smallest, Balanced, Best
  quality).
- "More settings" `<details>`, collapsed: firmware, OCR, layout, title, author, language and the
  font library. Everything else in today's Settings/advanced panels moves here unchanged in
  behavior, except the style values (preview font size, initial Focus Mode): those belong to the
  Reading style. The chosen saved style is the single source of style values at conversion start;
  the user changes them in Review. (Designer's call, from the builder check.)
- Primary button: "Start conversion (N files)", full width, with the total estimate under it
  ("About 14 min in total on this computer"). Disabled with the hint "Add a file to start." when no
  file is chosen.

**AI models not installed** (replaces today's blocking setup screen; designer's call): an
inline notice at the top of the settings column: "PDFs need the AI models (416 MB, downloaded
once)." with a "Download models" button and an inline progress bar plus the per-file log in a
`<details>`. While models are missing, PDF rows say they will convert with Layout set to Page
images, exactly as today's strings say. "Try again over IPv4" appears after a failed download, as
today. The size shown comes from `/api/setup`.

**Recent conversions**: a divided list, one row per job: name (and "and N more files"), date and
outputs, status as a word in its color (Done, Failed, Cancelled, Running, Queued), and an action
link ("Open" for done/running jobs, "Details" for failed ones).

## Screen 2 · Convert

Layout top to bottom:

1. **File queue** (only when the job has more than one file): pills per file with an icon and a
   word: "converting", "next", "waiting", "done", "failed", "cancelled". A done file's pill is a
   link to its Review.
2. **Title row**: file name, meta line (pages, kind, device, outputs). Right: the percent (large),
   "about N min left · M:SS so far", and a secondary "Cancel" button.
3. **Stage bar**: one segment per stage in `eco.events.STAGES` that this file will run, up to
   six. The set depends on input and options (`pipeline.py`): read/layout/fix only for PDFs, no
   `fix` for a page-images PDF, no `epub` stage for an EPUB input, no `epub` or `optimize` for
   XTC-only output, `xtc` only when XTC is chosen. The GUI derives the set from the same rules,
   and a stage that the server reports but the GUI did not expect is added, never dropped. Each segment has a
   6 px track and fill, the stage name under it, and a state line: "Done, 41 s", "214 of 412
   pages" or "In progress", "Waiting", "Already done" (the existing `state_reused`), or
   "Stopped" for a failed stage. Segment widths are proportional to the expected share of time
   (see Progress model). Below 700 px the bar becomes a vertical list with the same text.
4. Two columns:
   - **Page map** (PDF only): 12 px squares in an auto-filling grid inside a panel. Title "Pages ·
     214 of 412 read". Legend: Done, Working, Waiting, Has a finding. Caption: "Each square is
     one page. After the conversion, click a square to open that page in Review." Blank pages
     are drawn as Page done once the layout stage passes them, with the label "blank".
   - **Findings**: count in the heading, a divided list (page as a warning-colored label, then the
     message), newest last. Empty state "Nothing to report yet." Caption: "Review opens by itself
     when this file is done." Findings on page 0 (whole-book findings, all Markdown and EPUB
     findings) are labelled "Whole book" instead of a page.

**Which findings count** (designer's call): only `level == "warning"` findings are counted, listed
here and marked on page maps. `info` findings (blank pages, OCR pages and similar) are not marked;
Review lists them in a collapsed "Notes (N)" group under the warnings.

Behavior:

- The percent, the time left and the current stage are in a polite live region, updated at most
  every 2 seconds for screen readers; the visual updates follow every event.
- When the first file finishes, the GUI opens its Review automatically. Later files never pull
  the user out of Review: when one finishes, the Review top bar says "lecture-notes.md is ready to
  review" with a link, and the file select updates. While files are still converting, the top
  bar shows "Converting lecture-notes.md · 40%" with a "Show progress" link back to Convert (the
  Convert step in the header is also a link while the job runs). A later file's failure or a
  cancel appears in that same top bar status, in text, and in the file select ("failed",
  "cancelled").
- **Failure**: the running segment turns Error with "Stopped" and the panel shows the one-line
  error from the server in an alert. When no file converted, the actions are "Try again" (today's
  behavior: run the same files with the same settings) and "Back to Select". In a multi-file job
  the next file starts by itself. A file that fails does not block Review of the files that
  succeeded.
- **Cancel**: the button text becomes "Cancelling…", then the screen says "The conversion was
  cancelled." with "Back to Select". Files already converted stay reviewable.
- **Reload and Recent conversions**: the Convert screen is rebuilt from the job's event log
  (today's replay). The page map comes from the new `book` event (Backend changes); a job without
  it (older jobs) shows the stage bar and findings without a page map. A rebuild that reuses the
  extraction shows read/layout/fix as "Already done" and the page map fully done, from the `book`
  event stored with the reused extraction, or no page map when there is none.
- Durations ("Done, 41 s", "M:SS so far") come from the event timestamps (Backend changes), so
  they survive a reload.
- Markdown and EPUB inputs: no page map; the findings list takes the full width under the stage
  bar.

### Progress model

- Overall percent = the sum over stages of (stage weight × stage completion). Stage completion is
  1 when finished, `done/total` from page events while the stage reports pages, and 0.5 for a
  running stage that reports no pages. The shown percent never decreases and never shows 100
  before the file is done.
- Stage weights come from the same per-page rates the server already sends with `/api/inspect`
  (`seconds_per_page`) for the layout stage, and fixed shares for the others. Starting values,
  tunable by the builder: read 5 %, layout 55 %, fix 15 %, epub 10 %, optimize 8 %, xtc 7 %,
  renormalized over the stages this job actually runs.
- Time left keeps today's estimate logic; it is shown as "about N min left" or "less than a
  minute left", never with seconds.

## Screen 3 · Review

Layout top to bottom:

1. **Top bar**: a file select when the job has more than one file (each option says "reviewed",
   "review required", "converting" or "not converted"); a summary line (time taken, EPUB size
   with original size, XTC size, findings count in warning text). Right: the primary button
   "Continue to export".
2. **Page strip**: one thin bar per page, full width. Waiting/plain pages in Page digital at
   12 px high, pages with warning findings in Warning mark at 20 px, the current page in Accent
   at 28 px. Text above it: "Page 187 of 412" left, "Click any page to open it" right. For PDFs
   the strip counts source pages. For Markdown and EPUB it counts device pages and has no finding
   bars, because their findings are all on page 0; their findings list shows them as "Whole book".
3. **Three columns** (findings 240–280 px, original, device), wrapping below 1100 px:
   - Findings: buttons, the selected one with an accent border and tint and "· showing" after
     its page label. Clicking one moves both previews and the strip to that page (today's
     synchronized behavior). Caption explains the arrow keys.
   - Original: "Original PDF · page N" heading and the rendered source page. Findings carry no
     region data, so there is no outline on the page (the mockup's outline is dropped). Markdown
     inputs show today's source text pane.
   - Device: heading "On Xteink X4 · page X of Y", a segmented EPUB/XTC switch (only formats that
     were produced), the device frame with the preview image, then previous/next page buttons
     with "Approximate preview" between them. "View as" (CrossPoint, CrossInk, Stock) sits next
     to the format switch for EPUB.
4. **Reading style panel**: Text size, Line spacing, Side margins, First-line indent as labelled
   range inputs with their value; Focus Mode checkbox with a strength select (Low, Medium, High)
   that is disabled and removed from the tab order when Focus Mode is off. A changed control shows
   "· changed" after its value in accent color. Footer row: "Advanced typography" link (opens
   today's full style editor in a side panel; both surfaces edit the same values), a status line,
   "Discard" and "Apply to book".

Behavior:

- Moving a control updates the device preview through today's debounced live preview. It never
  rebuilds files.
- When any control differs from the applied style, the status says "N changes shown in the
  preview, not yet in the files", "Apply to book" becomes the screen's one blue button, and
  "Continue to export" is disabled with the hint "Apply or discard your changes to continue".
  While applying: "Applying… this rebuilds the files" in a polite live region; then the status
  clears and "Continue to export" is blue again.
- **What "Apply to book" does** (designer's call, keeping today's backend): it calls today's
  rebuild endpoint and today's single Apply logic (`applyChanges` in `review.js`). The rebuild
  is a new job that reuses the extraction, so it is quick. The GUI shows its Convert screen (the
  stage bar shows read/layout/fix as "Already done"), then returns to Review by itself, on the
  same file, page, selected finding, format and view. Reviewed marks carry over by file position
  and name for files whose output did not change; the rebuilt files need review again, and the
  file select says so. "Apply to book" is disabled while any file of the job is still converting,
  with the hint "Available when every file has converted". The rebuilt job appears in Recent
  conversions as today.
- "Continue to export" marks the file as reviewed in client state. For a multi-file job it reads
  "Continue to next file" and opens the next unreviewed file until every successfully converted
  file is reviewed. **Export is per job** and opens once every file has finished (done, failed or
  cancelled) and every successful one is reviewed; before that the button is disabled with the
  hint naming what is left ("lecture-notes.md is still converting").
- The left and right arrow keys turn the page unless focus is in an input, select or the style
  panel. The page strip is one focusable element with `role="slider"`, arrow keys, Home and End,
  and `aria-valuetext` such as "Page 187 of 412, has a finding".
- Returning from Export keeps page, selected finding, format, view and control values.

## Screen 4 · Export

A single 640 px column:

- Success mark, title "Ready to download", summary line: file name, page count, "reviewed, N
  findings seen", conversion time.
- **Files**: one row per output: file name, a description (format, what it is for, page count
  for XTC, size and original size for EPUB), and a download button. The first output's button is
  the screen's blue button; the others are secondary.
- **Checks**: one line per EPUB output, from the new `epubcheck` field (Backend changes):
  "EPUBCheck passed.", "EPUBCheck passed with 2 warnings." with a `<details>` listing the
  warnings (today these arrive as page-0 findings), or "EPUBCheck did not run, so this EPUB was
  not validated." A failed EPUBCheck never reaches Export: it fails the file today, and the file
  shows as failed in Convert and Review. Jobs without the field (older jobs) show no EPUBCheck
  line. A second line restates the applied style values ("Text size 20 px, side margins 12 px,
  Focus Mode medium"); no style name is shown, because none is stored with the job.
- **Other files** of the same job that still need review or are still converting, each with a
  link to it.
- Footer: "Back to Review", "Convert another book" (goes to Select), and "Delete this
  conversion" as a red text button with today's confirmation.

## Backend changes

Small, additive changes; existing fields keep their meaning.

1. `PageEvent` gains `page: int | None` (the source page number that just finished). The layout
   stage in `pipeline.py` fills it in both the Docling path and the page-images path; other
   emitters may leave it `None`. `jobs._event` adds it to the dict (`app._public_event` already
   passes page events through unchanged). When `page` is missing the page map fills squares in
   page order from the `done` count. Note that `total` counts non-blank pages only.
2. A new event, `BookEvent(pages: int, scanned: tuple[int, ...], blank: tuple[int, ...])`, emitted
   once by PDF conversions at the end of the read stage, from the `PageInfo` list the pipeline
   already has. It goes into the job's event log like the others, so a reload replays it. When
   the extraction is reused, the pipeline emits it from the reused extraction's page info if that
   is available without re-reading the PDF; otherwise it is skipped.
3. `describe_pdf` (`/api/inspect`) adds `scanned: list[int]` and `blank: list[int]` next to the
   existing `pages` and `scanned_pages`, for the Select page map.
4. Every event dict gets `t`, the server time in seconds (float) when the event was produced, set
   in `jobs._event` or where events are queued. The GUI uses it for stage durations and elapsed
   time.
5. Per EPUB output, the file's public info gets `epubcheck`: `"passed"`, `"passed_with_warnings"`
   or `"not_run"`, recorded where the validator runs (`src/eco/epub/validator.py` is called from
   the pipeline) and saved additively in `job.json`. Outputs and sizes are already public; nothing
   else is added there.
6. Previewing a finished file while a later file of the same job is still converting most likely
   works today (previews check only that file's outputs, and `job.json` is saved after each file).
   Add a test that proves it; fix it if the test fails.

## Responsive behavior

- Below 900 px: Select and Convert become one column; Review keeps original and device side by
  side and moves findings above them as a horizontal scrolling row of buttons.
- Below 600 px: Review stacks original above device; the style panel controls stack one per row;
  the stage bar becomes a vertical list; the header steps wrap under the brand.
- No horizontal page scroll at 360 px. Page maps reflow; the Review strip keeps one bar per page
  and, above 600 pages, groups pages so each bar is at least 1 px wide with a 1 px gap.

## Large books

- Page map square size: 12 px up to 600 pages, 8 px up to 1500, and above 1500 one square stands
  for a range of pages (label "Pages 1201–1210") so that at most 1500 squares are drawn.
- The page map is plain DOM (spans) with one update per event batch (`requestAnimationFrame`), not
  one reflow per event.

## Accessibility

- Native buttons, links, labels, fieldsets and headings throughout; no click handlers on spans
  or divs.
- Page maps on Select and Convert are `role="img"` with a text summary; their information is also
  in text nearby (counts, findings list). Clicking a page square is a mouse shortcut; the keyboard
  path to the same page is the findings list or the Review strip.
- Every range input has a visible label and value. Live regions: polite for progress and preview
  updates, `role="alert"` for errors.
- Visible focus ring (2 px Accent, 2 px offset) on every focusable element.
- `prefers-reduced-motion`: no animated fills; values change in place.

## Text

All UI text lives in `src/eco/web/strings.py`, in plain English, no emoji. New strings follow the
wording in this document and the mockup. Existing keys are reused where the meaning is unchanged.

## Designer's calls after the builder check

A builder check found open questions; the designer settled them inside the approved direction.
The owner can overturn any of them:

1. "Apply to book" keeps today's rebuild (a new job reusing the extraction), passes briefly
   through Convert and returns to Review on the same page; disabled while files still convert.
2. Later files never pull the user out of Review; their status shows in the Review top bar.
3. Export is per job, after every file has finished and every successful one is reviewed.
4. Page map data comes from a new `BookEvent` in the event log, so reloads and Recent
   conversions work; older jobs show no page map.
5. Only warning findings are counted and marked; info findings sit in a collapsed "Notes" group.
6. Events get server timestamps for durations.
7. No finding outline on the original page (findings carry no region).
8. The Select reading style is the only source of style values at start; Export restates values,
   not a style name.
9. "Try again" stays on the failure screen.
10. EPUBCheck outcome recorded as an additive `epubcheck` field; old jobs show no line.

## What is left to the builder

- Exact breakpoints within the ranges above, debounce timing, and the stage weights' fine tuning.
- How the side panel for "Advanced typography" is built, as long as it is one surface and does not
  cover the device preview at 1440 px.
- File and function structure inside the existing `static/*.js` modules.
- Test approach, following the existing `tests/web` patterns.

## Verification

- Full fast test suite and Ruff pass.
- Exercise the flow with a PDF with scanned pages, a Markdown file, an EPUB, a two-file job, a
  failed file, a cancelled job, a job with no models installed, and XTC output on and off.
- Check 1440, 1024, 768 and 360 px widths, keyboard-only use of every screen, visible focus, and
  reduced motion.
- Compare each screen with its mockup board.
