# Focus Mode weight, Focus Mode on Select, honest style UI, X4 Pro default

Date: 2026-11-21. Status: draft for the owner's approval.

## Intent

eco's targets are EPUB and XTC, with EPUB first, and the EPUB is read on Xteink devices only.
Focus Mode should look the same in both outputs, follow one fixed rule that the user does not have
to tune, and let the user choose how heavy the bold is. The GUI must not suggest that style values
change an EPUB when they do not. New users should meet Focus Mode on Select, with a short
explanation, and the device most owners use should be chosen already.

## Decisions (the owner's)

1. **Fixed rule for the bold letters** of each word, in EPUB and XTC alike:
   - 1 to 3 letters: 1 letter;
   - 4 letters: 2 letters;
   - more than 4 letters: 40% of the letters, rounded to the nearest whole letter (half rounds
     up): 5→2, 6→2, 7→3, 8→3, 9→4, 10→4, 12→5. *(Rounding is the designer's proposal; the owner
     did not object.)*
   A letter is a Latin, Greek or Cyrillic letter with its combining marks, as today. Low / Medium /
   High strength is removed.
2. **The user chooses the bold weight**: Semibold (600) or Bold (700). Medium (500) is not
   offered: on a reader font with only regular and bold, CSS shows 500 as regular and Focus Mode
   would vanish from the EPUB. Default: Bold 700 (today's look).
3. **Honest UI**: style values other than Focus Mode do not change the EPUB.
4. **EPUB readers are Xteink only.**
5. **Default device: Xteink X4 Pro.**
6. **Focus Mode can be switched on at the start, on Select**, with a "?" control that explains it.

## Design

### Style and outputs
- `PageStyle.focus_strength` is replaced by `focus_weight: int` with the choices 600 and 700,
  default 700 (`style.py` RANGES).
- Focus Mode needs a font weight heavier than the text weight: with text weight 600 only 700 is
  allowed; with 700 Focus Mode stays unavailable (today's rule and finding). For XTC with an
  uploaded font that lacks the chosen weight, the nearest heavier weight the font has is used.
- EPUB (`epub/focus.py`): the same `<b class="eco-focus">` markup, with `style="font-weight:600"`
  or `700`. One function computes the number of bold letters from the number of letters.
- XTC (`render/md2typst.py`): the Typst show rule uses the same count (written in Typst, since
  Typst cannot call Python) and `text(weight: <focus_weight>)`.
- One table of cases (word length → bold letters) is tested against both the Python function and
  the generated Typst rule.
- Old saved styles and old jobs that carry `focus_strength` still load: the key is ignored and
  `focus_weight` takes its default. CLI: `--focus-strength` becomes `--focus-weight {600,700}`.

### Select
- Under Reading style, a checkbox "Focus Mode" with a "?" button beside it. The button toggles a
  short explanation below the checkbox (a disclosure with `aria-expanded`, keyboard reachable, not
  a hover tooltip). Proposed text: "Bolds the first letters of each word so your eye finds words
  faster. Short words get one bold letter, longer words about 40%. It is written into the EPUB and
  drawn into the XTC. You can change the bold weight in Review."
- The checkbox starts as the chosen reading style says, and follows a change of that select. Its
  state is the `focus_mode` of the new job's style; the weight comes from the reading style.

### Review: honest about what changes the EPUB
- When the preview shows the EPUB, the dock shows one line under the range controls: "Text size,
  spacing and margins change the XTC and this preview. On the Xteink, the EPUB follows the
  reader's own settings." Focus Mode and its weight have no such line: they are written into the
  EPUB.
- Under the weight select, in the EPUB preview: "On a reader font without semibold, both weights
  look bold."
- A job with EPUB output only: Apply counts and applies only Focus Mode changes (on/off, weight).
  Other changes are labelled "preview only" and do not enable Apply. A job with XTC output keeps
  today's behavior, and the status says the other values change the XTC.
- Advanced typography gets the same note for EPUB-only jobs.
- README and README.id.md are corrected.

### Default device
- `Options.device` defaults to `x4-pro`; the device select on Select and `eco convert --device`
  default to it too. Consequence: a CLI run without `--device` now names its outputs
  `book.x4-pro.epub` instead of `book.x4.epub`.

## Approaches considered (Focus Mode in XTC)
- **Chosen: keep the Typst show rule and change its formula**, with one shared test table.
  Small change, render speed unchanged.
- Rejected: wrap every word in Python while writing Typst source (one implementation only), because
  the Typst source grows at every word and rendering gets slower, for little gain.

## Non-goals
- No typography CSS (font size, spacing, margins) is written into the EPUB; the owner chose the
  honest UI instead.
- No weights other than 600 and 700, and no per-word tuning.
- EPUB optimizations beyond this are a separate brainstorm.

## Left to the builder
- Exact strings beyond the proposals above, placement and styling of the "?" control within
  DESIGN.md's rules, and the decision log entry.
