# Xteink EPUB follow-ups: each TOC file, more page boxes, photo size

Date: 2026-11-21. Status: approved by the owner ("answer as you recommend") on 2026-11-21.
Builds on `2026-11-21-epub-xteink-optimizations-design.md` and its final review (M1, M7, and the
photo size growth).

## 1. Each contents file on its own (review M1)
- Before: the nav document and the NCX were judged as one pool; an EPUB 3 with a working nav and
  no NCX got no NCX, though it is not known which file each Xteink firmware reads.
- After: each is judged on its own (missing, no entries, or more than half pointing nowhere). A
  broken or missing one is written from the one that works, so the publisher's contents are kept
  in both; only when both are broken are they built from the headings. EPUB 2 still gets no nav.
  The finding says which file was written and from what.

## 2. More page boxes and the font shorthand (review M7)
- Before: only rules whose selectors were exactly `html` or `body` lost absolute margins;
  `body.calibre`, Calibre's `.calibre` body class, `@page`, a `<body style>` and `font: 9pt/14px`
  kept their absolute sizes.
- After: a page box is `html`, `body`, `body` with classes or an id (`body.calibre`), a class
  that the book puts on its `<body>` elements (`.calibre`), `@page` (with or without a page
  selector such as `:first`), and the style attribute of `<body>`. The `font` shorthand's size
  becomes `em` and its line height unitless, by the same rules as `font-size` and `line-height`.

## 3. Enhanced photos are no bigger
- Before: sharpening made every enhanced JPEG larger (16% on a real book).
- After: an enhanced photo is encoded at the profile's quality; when that is bigger than the
  same photo encoded without enhancement, the quality steps down by 2 until it is not, at most 15
  below the profile. Measured on the sample, a fixed drop could not hold the size at every level
  (small needed more than 12, best 4), so the step is per photo.

## Non-goals
No other optimization changes; `general` untouched.
