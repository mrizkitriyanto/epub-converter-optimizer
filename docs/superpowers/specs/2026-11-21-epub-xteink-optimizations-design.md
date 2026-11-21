# EPUB optimizations for Xteink: publisher CSS, colors, images, empty pages, contents

Date: 2026-11-21. Status: approved by the owner on 2026-11-21.

## Intent

The EPUB is eco's first output and it is read on Xteink devices only. On the Xteink the reader's
own text size, spacing and margins should rule, text should be as dark and sharp as e-ink allows,
pages should never be blank, and every book should have a working table of contents. The owner
chose five of the ten brainstormed ideas: 1, 2, 3, 5 and 6.

## Scope

All five apply only when the device is an Xteink (`x4`, `x4-pro`, `x4-classic`, `x3`), in the
existing optimizer (`src/eco/epub/optimizer.py`, `css.py`, `images.py`). They run for EPUBs eco
builds from PDF or Markdown and for EPUB inputs. `general` is untouched. Each change reports what
it did as an `info` finding, like the optimizer's other passes ("12 fixed font sizes made
relative", "3 empty pages removed").

## The five changes, before and after

### 1. Publisher sizes become relative (CSS)
- Before: a stylesheet sets `p { font-size: 9pt; line-height: 14px }` or `body { margin: 40px }`.
  The Xteink text size setting has no effect on those values; text can be tiny on a 4-inch screen.
- After: absolute `font-size` values (px, pt, pc, cm, mm, in) become `em`, taken against 16 px
  (12pt → 1em, 24px → 1.5em), so headings stay bigger than body text but everything follows the
  reader's size. Absolute `line-height` becomes unitless (14px at a 16px font → 0.875 → kept at
  least 1.2). Absolute `margin` and `padding` on `html` and `body` go; elsewhere a value above
  2em-equivalent (32px) is capped at 2em. Keyword sizes (`x-small` and so on) become em too.
- Approach chosen: convert, not delete. Deleting every size would flatten headings to body size.
- Cost: a book whose design relies on exact sizes looks a little different; it reads better.

### 2. Colors go (CSS)
- Before: `color: #777` text looks faint on e-ink; `background-color` boxes become gray blocks;
  white text on a dark box can vanish when only one of them survives.
- After: `color`, `background`, `background-color` and `background-image` declarations are
  removed together, so text is black on white everywhere. Border colors stay.
- Cost: syntax highlighting in code and colored callouts lose their color; their text stays.

### 3. Images tuned for e-ink
- Before: Xteink images are already grayscale and fitted to 480×800, but photos stay flat and
  muddy.
- After: photos (the JPEG path) get an auto-level (1% clipped at each end) and a light unsharp
  mask (radius 1, 50%, threshold 2). Line art and PNGs keep today's treatment. The cover gets the
  same treatment as photos.
- Cost: a slightly larger JPEG at times; noisy photos can show a little more grain, which is why
  the sharpening is light.

### 5. No blank screens
- Before: books converted by other tools often have empty paragraphs (`<p>&nbsp;</p>`), runs of
  `<br/>`, empty `<div style="page-break-after:always">`, or whole XHTML files that hold nothing.
  Each one can cost a blank screen when turning pages.
- After: an empty `p` or `div` (no text, no image, no `id`, nothing inside but white space,
  `&nbsp;` or `<br/>`) is removed, with any page break it carried. Runs of `<br/>` collapse to
  one. A spine document with no text and no image is removed from the spine; links, nav and NCX
  entries that pointed at it point at the next document in the spine.
- Cost: an intentionally blank page (rare in a reflowable book) is gone.

### 6. A working table of contents
- Before: an EPUB input without a nav document and NCX, with empty ones, or with entries whose
  targets are missing, cannot jump to chapters, and the progress bar's chapter marks are empty.
- After: when the contents are missing, empty, or more than half their entries point nowhere,
  eco builds them from the `h1`–`h3` headings of the spine documents in order (adding an `id` to a
  heading that has none). With no headings, one entry per spine document, named by its `<title>`
  or "Section N". Both a nav document and an NCX are written, since it is not known which one each
  Xteink firmware reads. A working table of contents is never replaced.
- Cost: a rebuilt TOC can be flatter or more detailed than the publisher meant.

## Order inside the optimizer
CSS (1, 2) runs where the CSS is rewritten today (`_references`). Images (3) in `_images`. Empty
elements and documents (5) before the chapter split, so a split never makes a part of nothing.
Contents (6) after (5) and after the split, so its links point at the final files. Focus Mode
stays after all of them.

## Non-goals
- No change for `general`. No hyphenation, typography, cover resizing or landscape rotation (not
  chosen). No user switches for these five: they are the Xteink profile.

## Left to the builder
- The exact capped values in 1 within the stated rule, the finding wording, and test fixtures (a
  small EPUB per change in `tests/fixtures`).
- Whether the "keep the original image when it is smaller" shortcut still applies to photos once
  they are enhanced: it must not skip the enhancement.
