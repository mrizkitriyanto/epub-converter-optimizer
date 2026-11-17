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

## 2026-11-17: Model setup downloads only what conversion uses

- `eco setup` fetches three models, about 417 MB in all, into `<data>/models`, in the folders that
  Docling's `artifacts_path` reads:
  - layout: `docling-project/docling-layout-heron` at commit `8f39ad3c`, only `*.json` and
    `*.safetensors`;
  - tables: `docling-project/docling-models` at commit `fc0f2d45` (tag v2.3.0), only
    `model_artifacts/tableformer/accurate/*`;
  - OCR: RapidOCR for `onnxruntime` in Docling's default language. The rapidocr version in
    `uv.lock` pins its download URLs.
- It does not call Docling's `download_models`. That one also fetches RapidOCR's torch weights
  (`.pth` pickles), an unpinned ONNX copy of the layout model and the fast TableFormer.
- Model files must end in `.safetensors`, `.onnx`, `.npz`, `.json`, `.txt`, `.yaml`, `.yml` or
  `.md`. Everything else is refused, except huggingface_hub's bookkeeping in
  `<repo folder>/.cache/huggingface/` and eco's `.complete` marker.
- Each RapidOCR file is checked against the SHA-256 in rapidocr's registry after every download
  attempt, including files that were already on disk. Docling's helper saves an HTTP error page
  as the model and later skips any file that exists, so without this check a bad file would stay
  for good. A file that does not match is deleted and the attempt counts as failed. A file with
  no SHA-256 in the registry is refused. The three files eco uses all have one.
- Retries (up to 8 attempts, waits of 2 to 60 s) cover network errors and OCR files with the
  wrong SHA-256. The network errors are connection and timeout errors from httpx, requests and the
  standard library, and HTTP 429 or 5xx from the Hub. Other errors stop at once. Files that
  finished downloading are kept between attempts.
- Known limit (R-34, accepted for M1): huggingface_hub 1.33 cannot resume a partly downloaded
  file in a later attempt. It resumes only within one attempt, and only after connect errors,
  timeouts and protocol errors. If a connection reset cuts a file off mid-download, the next
  attempt downloads that whole file again. For the 213 MB TableFormer file that can mean many
  minutes. eco has no Range downloader of its own. The first real `eco setup` on the owner's
  network will show whether one is needed. The spike downloaded the same files on that network.
- eco imports `huggingface_hub` (Apache-2.0), `httpx` (BSD-3-Clause), `requests` (Apache-2.0)
  and `rapidocr` (Apache-2.0) directly, so they are listed in `pyproject.toml`. All four were
  already in the lock through Docling.

## 2026-11-17: Code blocks come from the PDF text layer

- Docling's text for a code block loses indentation, so `fix_code_blocks` rebuilds the lines from
  the PDF text layer. PDFium collapses runs of spaces, so the indent comes from the x position of
  the visible chars: `round((line_x0 - min_x0) / median_char_width)` spaces. A gap inside a line
  becomes one space when it is wider than half a char.
- It uses PDFium's loose char boxes. Their top, left and width come from the font metrics, so line
  grouping (2 pt) and the char width do not change with the glyph shape. On the code fixture the
  tight boxes spread one line over 2.3 pt and give a 4.48 pt median width, so the 24 pt indent
  would come out as 5 spaces.
- On a scanned page there is no text layer. The code block is cropped to
  `images/p{page:04d}-code-{n}.png` and becomes an image with the old text as alt text.

## 2026-11-17: Code block with no text layer chars keeps Docling's text and warns

- When `reextract_code` finds no chars on a page that is not scanned, `fix_code_blocks` keeps
  Docling's text and records a `code_not_restored` warning (spec section 8.4, item 2). Same text
  as before records nothing.

## 2026-11-17: Region crops: colour, format by content, picture pages

- Formulas are cropped in grey. Pictures, table twins and page images are cropped in colour,
  because spec section 8.8 keeps colour on `general`; the optimizer greys them for Xteink.
- Picture crops and page images are saved as PNG when `_is_line_art` says so, and as baseline JPEG
  at quality 92 otherwise. Formulas and table twins are always PNG. The optimizer keeps PNG
  sources as PNG on `general`, so a photo saved as PNG would ship at about 10x its JPEG size.
- A page becomes one page image (alt "Page <n>", `page_as_image` info finding) when its picture
  blocks, clipped to the page, cover more than 80% of the page area and the page has fewer than
  200 chars. The area comes from Docling's picture blocks, not `PageInfo.image_ratio`, so vector
  diagrams count and OCR'd text scans do not.

## 2026-11-17: Text clean-up rules: vocabulary dehyphenation, protected short words

- `dehyphenate` joins `a- b` only when the joined word occurs in the book's vocabulary (every word
  of every paragraph, fragments included); otherwise it writes `a-b`. The plan's extra clause "or
  neither part is" cannot fire under that vocabulary, so it is not implemented.
- `clean_heading_artifacts(text, lang=None)` never drops a real short word of `lang` (Indonesian
  `di`, `ke`; English `a`, `an`, `in`, `of`, ...). Without it, "Pergi ke Kelas" lost "ke" and
  "History in India" lost "in", which spec section 5 forbids (content lost without a warning).
  The pipeline passes the detected language; `lang=None` protects nothing.
- The glued-first-letter rule stays as planned. It turns "Pakai iPhone" into "Pakai Phone" in an
  OCR heading; that is a known limit.

## 2026-11-17: Heading levels: in-order bookmark matching, no finding for out-of-range bookmarks

- `assign_heading_levels` walks the bookmarks in order. Each takes the best unmatched heading
  within one page (ratio of at least 0.8), and a heading matches at most one bookmark. A later,
  better bookmark does not take a heading from an earlier one.
- An unmatched bookmark adds a heading (`heading_added` info) only when its page lies between the
  lowest and highest block page. With `--first`/`--last` the other bookmarks are skipped silently.
- Without bookmarks, ALL-CAPS (at least 4 letters) and `Chapter`/`Bab`/`BAB` headings get level 1;
  the rest get level 2.

## 2026-11-17: Docling adapter: what the mapping keeps, and how tables come out

- Items with no text are dropped, except formulas, pictures and tables. Docling leaves a formula's
  `text` empty and puts the text-layer text in `orig`, so a test on `text` alone would drop every
  formula before `materialize_regions` can crop it.
- A `document_index` item (a contents page) is a table item with no text, so it maps to a table.
  A caption that no table or picture owns is dropped, as the plan says.
- docling-core 2.107.1 ignores `add_caption` in `TableItem.export_to_html(doc)`. The call stays as
  the plan has it, so the table HTML holds the caption as `<caption>`. That is how a table caption
  reaches the book, because `write_book` renders `Block.caption` only for images. A footnote that
  belongs to a table is also in that HTML and comes out again as a `footnote` block, so it appears
  twice.
- Docling catches and logs any exception a progress callback raises (`ProgressReporter._emit`), so
  `on_page` cannot stop a conversion by raising.
