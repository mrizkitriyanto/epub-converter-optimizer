# Decision log

Short dated entries. The design spec (`docs/superpowers/specs/`) holds the full reasoning.

## 2026-11-16: Docling is the PDF engine

Chosen after the PDF engine spike (`docs/research/2026-11-16-spike-pdf-engines.md`).
Docling is MIT licensed. PyMuPDF and other AGPL or GPL tools are avoided.

## 2026-11-16: GUI before XTC

Order of work: core and CLI (M1), web GUI (M2), XTC output (M3), Docker and release (M4).
The owner chose to build the GUI before XTC output.

## 2026-11-17: Provisional device values

These values are safe defaults until the owner checks them on a real device.
All three are pending device verification by the owner.

- Chapter size limit: 100 000 bytes.
- CSS `white-space: pre-wrap` is assumed to be supported by the CrossPoint firmware.
- XTC header layout follows CrossPoint `XtcTypes.h`.

## 2026-11-17: Optimizer choices

- On `general`, embedded fonts are subset with fontTools (MIT) to the characters of the book and
  their upper and lower case forms (CSS `text-transform` and small caps show them), keeping every
  OpenType layout feature. WOFF2 needs brotli, which is not a dependency, so a WOFF2 font stays as
  it is, with an info finding.
- An SVG cover wrapper becomes an `<img>` on Xteink only. On `general` it stays, with its `viewBox`
  fit to the page (spec §8.8).
- On Xteink, a chapter over the limit is cut between the children of the body, or of the single
  wrapper (div, section, article) that holds the body. The cut leaves 5% of the limit free for the
  links that point into other parts.
- A manifest item is dropped only when its file name appears nowhere in the book. When in doubt it
  stays.

## 2026-11-17: pypdf as a dev dependency

`pypdf` (BSD-3-Clause, 7.1.0, 419 KB wheel) is in the `dev` group only. Tests use it to build an
encrypted PDF and a PDF with bookmarks and metadata at test time. The encrypted fixture uses RC4-128
because pypdf's AES needs `cryptography`, which is not in the lock; PDFium reports the same password
error for either.
