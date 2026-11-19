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

- Items with no text are dropped, except formulas, pictures and tables (R-46). Docling leaves a
  formula's `text` empty and puts the text-layer text in `orig`, so a test on `text` alone would
  drop every formula before `materialize_regions` can crop it.
- A `document_index` item (a contents page) is a table item with no text, so it maps to a table.
- A caption that a table or picture owns is not a block of its own: its text is in the table HTML
  or in the picture's `Block.caption`. Any other caption is a `paragraph` in its place in reading
  order (R-50). The plan dropped such captions, but spec section 5 allows no content lost without
  a warning. A caption of a code block follows the code block as a paragraph. It does not go into
  the code block's `Block.caption`: `write_book` renders a caption only for a block that has an
  image, so a code block that stays text would lose it (R-51).
- docling-core 2.107.1 ignores `add_caption` in `TableItem.export_to_html(doc)`. The call stays as
  the plan has it, so the table HTML holds the caption as `<caption>` and its footnotes after
  `</table>`. That is how a table caption reaches the book, because `write_book` renders
  `Block.caption` only for images. The HTML also holds the items of a rich cell (an item group
  that a cell points to; Docling makes one for a table it finds no grid in and for a cell that
  holds a picture). So no item under a table is a block of its own (R-52), or its text would be in
  the book twice. R-48 skipped only the footnotes. A picture in a cell is the exception, because
  the HTML has no image: it stays a `picture` block and follows the table. Docling leaves a
  picture that owns a caption or a footnote out of the cells (`_match_table_pictures`), so such a
  picture has nothing to repeat. Free footnotes and footnotes owned by code stay `footnote`
  blocks.
- Field items under a table exist only with the Docling option `extract_form_fields`, which eco
  leaves off. They are skipped with the rest, but the table HTML does not carry them: for a field
  region it writes an HTML comment. Turning that option on needs a new decision.
- `iterate_items` goes into a picture only for its captions, so it never yields a footnote the
  picture owns. `_to_blocks` adds each one as a `footnote` block right after the picture, with the
  page and box of its own provenance or, without one, the picture's (R-49; spec section 5 allows no
  content lost without a warning). Text inside a figure stays out.
- `on_page` is called only for pages Docling finished without error (R-47). Task 17 compares the
  pages it asked for with the pages reported and warns about each missing one (`page_failed`).
  Docling catches and logs any exception a progress callback raises (`ProgressReporter._emit`),
  so `on_page` cannot stop a conversion by raising; Task 17 checks `cancel` between chunks.

## 2026-11-17: Pipeline: the extraction cache holds the PDF, not the output options (R-45)

- The extraction of a PDF is cached as `<data>/cache/<sha256[:16]>-x<EXTRACTOR_VERSION>-<ocr>.book`.
  The key is the PDF's hash, the extractor version and `--ocr`. Device, firmware, size, title,
  author and language do not change the extraction, so changing them runs neither Docling nor OCR
  again (spec section 8.2).
- The front matter of the cached book comes from the PDF alone: title and author from the PDF
  metadata (the title falls back to the file stem), the language detected from the first 5000
  characters of the text, and `source` as the file name plus the SHA-256 (spec section 8.5; the
  builder makes `dc:identifier` from it). `--title`, `--author` and `--lang` are applied on top of
  the metadata at build time, for PDF, Markdown and book folders alike. If they went into the cached
  book, a later `--title` would be ignored; if they went into the key, a new title would run Docling.
- The key is the content of the PDF, not its name, so a renamed or copied PDF reads the same cached
  book. The file name must not leak through it: for a PDF without a title, `convert_file` sets the
  title to the stem of the current file at build time, before `--title` is applied. The cached
  `book.md` keeps the stem of the first extraction, and so does `source`, which names the file the
  book was first made from (that keeps `dc:identifier` the same for every copy).
- `write_book` writes `report.json` last, so a folder without it is what a cancelled or crashed run
  left behind. It is deleted before the next extraction. A folder with one is reused, and its
  findings are reported again.
- A page that was asked for and that Docling never reports as finished becomes a `page_failed`
  warning (R-47). A blank page becomes a `blank_page` info finding, a scanned page an `ocr_page` one
  (unless `--ocr off`).

## 2026-11-17: Pipeline: a cancel takes effect between chunks

- Docling runs over the non-blank pages in chunks: each run of consecutive pages is cut into pieces
  of at most 50. It swallows an exception raised in its progress callback, so `cancel()` is checked
  before and after each chunk and raises `Cancelled` there. In M1 a cancel waits for the chunk that
  is running: up to 50 pages, and longer when they are scans. The web GUI (M2) will cancel faster by
  stopping a worker process (spec section 8.2).

## 2026-11-17: Pipeline: `--mode reflow` is `auto` in M1; page images on `general` (R-10, R-9)

- Known gap: the spec names `--mode reflow` but does not say how it differs from `auto`, and no
  pass has a switch for it. In M1 `reflow` behaves like `auto`. Telling them apart needs a flag in
  the fix stage and `mode` in the cache key.
- `--mode pages` on a PDF builds a temporary book folder (never cached) with one image per screen of
  every non-blank page, then builds and optimizes it like a book folder. Xteink devices use their
  fixed screen. A `general` device has none, so its screen is `max_w` of the image profile by
  100 000 px: a page stays one image. The optimizer still fits every image into `max_w` by `max_h`
  (equal on `general`), so such a page ends up at most `max_w` px on its long side.

## 2026-11-17: Output names never overwrite an input

- The output is `<out dir>/<stem>.<device>.epub`. A stem that already ends in `.<device>` loses it
  first, so converting `book.x4.epub` again gives `book.x4-1.epub`. While the path is the same file
  as any input of the batch (paths resolved, plus `samefile` for hard links and case-insensitive
  names), `-1`, `-2` and so on are added before the extension.

## 2026-11-17: Docling adapter: the slow tests on the real models (R-53)

- The first run on the installed models showed that Docling 2.150.1 does not label the synthetic
  code fixture as `code`. Its layout model (heron) does not treat a short listing without a
  background as code, so the listing comes back as one `paragraph` that holds the four listing
  lines of the synthetic code fixture joined on one line, with bbox (18.0, 137.0, 216.7, 189.3).
  The fixture's box is (16, 135, 218, 192), so the coordinate space is right. The synthetic formula also comes
  back as a `paragraph`. On the real Forensic, Malware and ResNet pages the spike saw `code` and
  `formula` items (`docs/research/2026-11-16-spike-pdf-engines.md`, experiments 1 and 2).
- The two slow tests on the code fixture therefore do not ask for `kind == "code"`. One checks that
  a single block holds every line of the listing, compared without white space because Docling
  merges the lines. The other takes the block that holds the fixture's second listing line and
  checks its box to 10 pt. The `code` label is checked by acceptance criterion 3 (spec section 9) on the real Forensic and
  Malware pages.
- The pytest config ignores three `DeprecationWarning`s that Docling raises when its own code reads
  its deprecated options: `force_full_page_ocr`, `generate_table_images` and `rec_font_path`. eco
  sets none of them. Each filter matches the whole message, and the one whose message is the single
  word `deprecated` also matches the module. Any other warning still shows.

## 2026-11-17: The CLI: errors, names and folders (Task 18)

- An error prints one line, `error: <message>`, on stderr, with no traceback. `eco convert` goes on
  with the next file and exits 1 at the end if any file failed. `eco setup` and `eco extract` print
  the same line and exit 1. A usage error exits 2.
- `--landscape` with `--device general` is a usage error: landscape only means something on a fixed
  Xteink screen. A bare `eco` is a usage error too, and exits 2. `eco --version` exits 0.
- A batch never overwrites an input or another output of the same run: `convert_file` gets every
  input and every output already written as `inputs`, so `a.pdf` and `a.md` give `a.x4.epub` and
  `a.x4-1.epub`.
- `eco extract` copies the cached book folder to `<dir>/<stem>.book` and never overwrites an
  existing one, because the user may have edited it: it takes the next free `<stem>-1.book`, `-2`
  and so on.
- The cache holds the file name its first extraction saw. For a PDF without a metadata title,
  `eco extract` rewrites the `title` in the copied `book.md` to the current file stem, so a renamed
  scan is not titled after its old name.
- A folder given to `eco convert` expands to the `*.pdf`, `*.md` and `*.epub` files and `*.book`
  folders in it, without recursion, in sorted order, but skips `<stem>.<device>.epub` for every
  device: those are earlier outputs, and converting the folder twice must not pile up `-1`, `-2`.
  A file named on the command line is always converted.
- Input and output paths and `--data` get `expanduser()`, so a quoted `"~/x"` never creates a
  folder named `~`.

## 2026-11-17: OpenCV is pinned below 4.13

- `rapidocr` pulls in `opencv-python-headless` with no cap, so the lock held 5.0.0. On Apple silicon
  its resize goes through KleidiCV 26.03, and the 258-page *Bicara* OCR run segfaulted at page ~200
  (exit 139) inside `kleidicv_resize_generic_stripe_u8`, called from RapidOCR's preprocessing in a
  worker thread. The crash is not deterministic.
- 4.12.0.88 on macOS arm64 has only the carotene HAL, no KleidiCV, and finished all 258 pages. KleidiCV
  is ARM-only, so Windows and Linux x64 just move to the same version: one OpenCV for every OS, and CI
  tests what the Mac runs. `tests/test_dependencies.py` fails if the pin is lost or a KleidiCV HAL
  comes back.
- The pin is a direct dependency (`opencv-python-headless>=4.12,<4.13` in `[project] dependencies`),
  not a uv constraint, so `uv tool install` and pip installs get it too. `numpy<2.3` comes with
  OpenCV 4.12's own metadata: the lock moved numpy 2.5.5 to 2.2.6.
- `uv.lock` is now revision 5 and needs a recent uv (0.13.9 wrote it).
- Cost: 4.12 lags 5.0 on fixes. Revisit when an upstream KleidiCV fix ships. The fallback is
  `cv2.setNumThreads(1)` on 5.0, which passed once on the Mac.

## 2026-11-17: Reading order: a narrow centred block spans both columns (R-13)

- In `is_multicolumn`, a block that crosses the vertical centre line of the page (`x0 < W/2 - 6` and
  `x1 > W/2 + 6`) counts as a spanning block, like a full-width one, and does not disqualify the
  page. Real papers, such as the ResNet sample, have centred title and author lines that are
  narrow. With the plan's literal rule they fall in neither column, the page is never detected as
  multi-column, and acceptance criteria AC4 and AC5 would depend on Docling's own order, which is
  wrong on those pages.
- If it turns out wrong: the T12 unit test passes either way, because its title and author blocks
  are full width. Revert to the literal rule.

## 2026-11-17: Image rules: minimum size, output format, transparency, never bigger (R-15, R-19, R-24, R-25)

- `ImageProfile.min_px` is 20 for Xteink and 0 for `general`. `transform_image` removes an image
  only when its width or height is below `min_px`. Spec section 8.8 keeps images under 20 px on
  `general` and removes them on Xteink; the plan's Global Constraints scope the rule to Xteink and
  its Task 7 text dropped that scope.
- `png_line_art` keeps its value `False` on `general`, and the flag means this. True (Xteink): the
  format follows the content, line art to PNG and everything else to baseline JPEG. False
  (`general`): PNG and GIF sources become optimized PNG, every other source becomes baseline JPEG at
  the profile quality (spec section 8.8, row `general`).
- On `general`, PNG output keeps its transparency. Alpha is flattened to white only for JPEG output
  and on Xteink. Flattening on `general` would put white boxes on dark or sepia themes.
- `transform_image` never makes an image bigger. When no resize is needed and the source is already
  in an acceptable final form (PNG or baseline JPEG; on grayscale profiles also mode L or 1 without
  alpha), it returns the smaller of the source bytes and the re-encode. On `general`, grey sources
  stay grey (L and 1 to L, LA to LA). Re-encoding L, 1 and P PNGs grew them by 39% to 84% in
  measurements.
- If any of it turns out wrong: each rule is one field, one branch or one comparison. Drop the size
  comparison, the transparency branch or `min_px` on its own.

## 2026-11-17: Pictures are cropped from a render at scale 3, clamped to the page (R-17, R-31)

- Picture crops come from rendering the page at scale 3 (about 216 dpi), not from the embedded
  raster at its native resolution (spec section 8.4, item 5, "source resolution"). Rendering also
  covers vector figures, and the optimizer shrinks every image to the device or to 1600 px anyway.
  If it turns out wrong: extract embedded rasters with pypdfium2 `PdfImage` for pictures that are
  pure raster.
- `crop()` clamps the pixel box to the rendered page. Inside the page the formula is unchanged.
  Pillow fills an out-of-bounds crop with black, so a block at the page edge would get black bars
  in the EPUB. If it turns out wrong: remove the clamp.

## 2026-11-17: Book folder: a missing report is empty, any block with an image is an image (R-20, R-21)

- `read_report` returns `[]` when `report.json` is missing, because spec section 8.5 makes a
  hand-made `.book` folder valid input. If it turns out wrong: callers check that the file exists.
- A block of any kind except `table` with a non-empty `image` is written as an image, with the text
  as alt text, or the kind when there is no text. Spec section 8.5 says formula and code crops live
  in `images/` and the book folder stands alone, and Tasks 13 and 14 already turn such blocks into
  `image` blocks. This replaces the earlier rule that unlisted kinds become paragraphs, and it
  guards against losing an image path without a warning. If it turns out wrong: one condition.

## 2026-11-17: EPUB builder: text cover, bare ampersands, no front matter plugin (R-16, R-22, R-23)

- When a book has no cover, `build_epub` draws a plain text cover with the title and author, in
  Pillow's built-in scalable font (`ImageFont.load_default(size=...)`). Spec section 8.7 asks for
  it for Markdown without a cover, and the plan left it out. If it turns out wrong: delete about 20
  lines.
- A bare `&` in raw HTML becomes `&amp;` before the XML check, as void tags are already normalised.
  A bare `&` is legal HTML. Without this, a table cell such as `R&D` makes the whole table fall back
  to escaped text. If it turns out wrong: one regex.
- The builder does not use the `front_matter_plugin` of mdit-py-plugins. `BookSource.markdown` never carries
  front matter, because `load_source` strips it, so the plugin could only misfire on a leading `---`
  thematic break: it would drop body text and leave an empty `front.xhtml` in the spine. Nothing
  changes if this is wrong.

## 2026-11-17: Optimizer: stock firmware warning, cover image kept (R-26, R-27)

- Provisional (R-26): when the firmware is `stock` on an Xteink device and the output still has
  images, the optimizer adds one warning finding that stock firmware does not show EPUB images. The
  images stay so the file is useful after a firmware change. When `small` with `stock` drops the
  images, it adds one info finding with the count (spec section 8.8, last bullet). Whether stock X4
  Pro and Classic show images is unverified; the device test is deferred. If stock firmware shows
  images: delete the two findings.
- `drop_images` never drops the cover image (the manifest `cover-image` item or the
  `<meta name="cover">` target). The cover is transformed like any other image, because the library
  view needs a cover thumbnail. If it turns out wrong: drop it with the rest.
- Related entries: R-14 (fontTools subsetting on `general`) and R-29 (SVG cover wrapper unwrapped on
  Xteink only) are in "Optimizer choices" above. R-14 adds that a font that fails to subset stays
  unchanged, and that `fonttools` (MIT, spec section 6.3) is a direct dependency; without the step
  both go.

## 2026-11-17: Acceptance tests: RAM on Windows, the AC2 time, EPUBCheck on every output (R-55, R-56, R-58)

- On Windows the harness takes the peak RAM of a conversion from `PeakWorkingSetSize`
  (`GetProcessMemoryInfo`) on the handle `Popen` still holds after the child has exited; POSIX keeps
  `os.wait4`. The `python.exe` of a venv only starts the base interpreter and waits, so a handle on
  it read 5 MiB for a child that touched 300 MiB. The harness starts the base interpreter with
  `__PYVENV_LAUNCHER__`, as `multiprocessing` does (bpo-35797), and a fast test with a 300 MiB
  child pins it. If it turns out wrong: the Windows working set and the macOS RSS are not the same
  figure, so re-measure AC2 and AC6 on the Mac.
- AC2's 900 s is defined for an M3 Mac. A run within 900 s passes on any machine. Over 900 s it
  fails on macOS arm64 and is skipped elsewhere as "not comparable", with the seconds, CPU and RAM
  in the reason. `TIMEOUT` is 4 hours and only stops a hang. If it turns out wrong: a real slowdown
  shows only when the Mac measures it.
- Criterion 7 is checked on every output of the suite (all six conversions use the default device,
  `x4`): no progressive JPEG, no image over 480x800, no font, SVG, WebP or GIF, `mimetype` first
  and stored, and EPUBCheck 5.4.0 without errors when `ECO_JAVA` and `ECO_EPUBCHECK_JAR` name a
  Java and the jar. Without them the EPUBCheck tests are skipped. If it turns out wrong: extra
  minutes per run; drop the extra outputs.
- The code listings that AC3 compares with are read from `samples/ground-truth/` and a missing file
  skips the test, so the public repo holds no book text. On Windows the models folder is linked into
  each fresh data folder with a junction, which needs no admin rights.

## 2026-11-18: Headings: a chapter label matches a bare chapter number (AC1)

- When the fix stage matches a PDF bookmark to a heading, a leading "Chapter N:" or "Bab N" in
  either title is read as "N" before the two are compared. A bookmark often says "Chapter 3: Title"
  where the page says "3 Title". With a short title the plain comparison stayed under 0.8, so the
  chapter got a second heading from the bookmark and its own heading became a stray one: six
  chapters of the Threat Hunting sample opened with their title twice. The number is kept, so
  "Chapter 3" never matches "12". If it turns out wrong: compare the titles as they are again.
- `EXTRACTOR_VERSION` is 2, so a book folder cached before these fixes is extracted again.

## 2026-11-18: Docling adapter: a hyphen of the text at a line end stays (AC1)

- Replaced by "Every line-end hyphen follows the spec's rule (R-72)" below.
- Docling joins the lines of a block and drops every hyphen that ends a line between two word
  characters, taking it for a word split by hyphenation. eco first joins a line to the next one,
  keeping the hyphen, when the word before the hyphen already holds a hyphen, slash or dot (a
  compound, a URL, a file name) or when a digit stands on either side of it. Hyphenation splits
  none of these. Before, `end-of-` and `season` became `end-ofseason`, URLs broke, and `ResNet-`
  `34` became `ResNet34`. The rule fires 5 times in the Threat Hunting sample's text layer, 7 in
  Forensic, 24 in Malware and 8 in ResNet, and in each case read by hand the hyphen belongs there.
- Every other line-end hyphen is still Docling's to join, so most hyphenated words are rejoined
  as before. Two cases stay wrong: a compound broken at its only hyphen (`well-` and `known`) and
  an em dash at a line end, which Docling's parser reports as `-` (3 of the 9 glued words in
  Threat Hunting). A scanned book whose typesetting splits a word that already holds a hyphen
  (`masing-ma-` and `sing`) would now keep that hyphen.
- It runs through `PdfFormatOption(pipeline_cls=...)`: a subclass of Docling's PDF pipeline whose
  page assembly applies the rule before Docling's own join. If it turns out wrong: drop the
  pipeline class.

## 2026-11-18: Every line-end hyphen follows the spec's rule (R-72)

- The fix stage's `dehyphenate` decides every hyphen or en dash that ended a line, in the prose
  of every block (not the text of code, a formula or an image, which is no prose; a caption is),
  against the words of the whole book (spec section 8.4.6). The split joins when the
  joined word appears elsewhere, or when a fragment appears nowhere else as a word of its own (the
  fragments at line breaks do not count). Otherwise the hyphen stays, with no space. A digit on
  either side, or a word that holds "/" or ".", keeps its hyphen; with a capital after the break,
  only the joined word decides; a word that already holds a hyphen is decided on its last part, so
  `masing-ma-` and `sing` join to `masing-masing` and `end-of-` and `season` keep `end-of-season`.
- Docling joined such hyphens itself in two places, the page assembly (`sanitize_text`) and the
  reading order's merge of a text that a page or column break cut. The adapter's pipeline class
  keeps the hyphen and the line break in both (`guru-` newline `guru`), and so does
  `join_split_paragraphs` at a page end, so `dehyphenate` sees every split. Docling's join had glued
  at least 20 reduplications in Bicara (`guruguru`) and dozens of compounds in the digital samples
  (`selfencrypting`, `antidebugging`).
- A table cell has no line breaks: Docling's table model joins its words with spaces. There the
  rule applies to a hyphen between letters or digits with a space after it (`password- protected`,
  and `512- byte`, which keeps its hyphen by the digit rule: `512-byte`). In other
  text a hyphen inside a line is left alone (`-rw-rw-rw- 1`, `first- and second-order`).
- Measured on the text layers of the digital samples: Forensic 778 line-end hyphens, 733 joined
  and 45 kept; Malware 2079, 1933 and 146; Threat Hunting 9, all kept (URLs, compounds, and em
  dashes that Docling's parser reads as "-"). Read by hand, the joins sampled were right, and 10
  keeps are wrong because both fragments occur elsewhere as tokens of their own (`com-ing`,
  `PCM-CIA`, `forward-ing`, `pre-tend`, `hall-mark` and the like). If it turns out wrong: change the
  vocabulary test in `dehyphenate`.
- `EXTRACTOR_VERSION` is 3.
- Added the same day: an em dash at a line end goes through the rule as well. OCR read a hyphen
  at a line end of Bicara as an em dash (`se—` and `karang`), and Docling joined it with a space.
  An em dash joins only when the joined word appears elsewhere in the book, as with a capital after
  the break (R-79): `sekarang` is common, so `se—` and `karang` join, and a real em dash stays with
  no space (`spend—this`, `result—unprecedented`) even when a neighbour is a word the book has only
  once. The 16 line-end em dashes of the three digital samples are all kept. Table cells keep the
  hyphen and en dash only, since a spaced em dash there is punctuation. `EXTRACTOR_VERSION` is 5.

## 2026-11-18: OCR: no line classifier, and each crop read at its own size (R-71)

- RapidOCR runs with `use_cls=False` and Docling's `detect_orientation=True`. On Bicara pages 83-84
  the line classifier turned 4 of 42 upright lines upside down (scores 0.51-0.64), and their text
  came out as garbage with no finding. Without it, the real pipeline read all of them right
  (0.97-0.99) and every other line the same. Docling's check of a whole region reads a region
  that reads badly again at 90, 180 and 270 degrees, which covers a page scanned upside down.
- `Det.limit_side_len` is 32 instead of 736 (`limit_type: min`). RapidOCR scaled every crop up
  until its short side was 736 px, so a one-line heading crop (93 px high) went up about 8 times
  and its line came back as overlapping pieces: "1. Respons yang Membuat Tersentuh" read
  "1.1 Respons s yang Membuat Tersentuh". At its own size, 216 dpi, the crop reads whole, and the
  other 13 crops of pages 83, 84 and 87 read the same words. A full-page crop was never scaled up,
  so this setting does not change `--ocr force`; the other two, no line classifier and the check
  of the whole region, apply to `--ocr force` as well.
- If it turns out wrong: drop the three settings in `docling_adapter._OCR`.

## 2026-11-18: EPUB: text that XML cannot hold becomes U+FFFD, with a finding (R-73)

- The builder replaces every character that XML 1.0 cannot hold (C0 controls, lone surrogates,
  U+FFFE, U+FFFF) with U+FFFD where the text enters it: in each line of the Markdown and in the
  metadata, which every XHTML, NCX, nav and OPF file is made of. A `xml_char_replaced` warning
  names the count and the chapter (or "the book's metadata"). It used to delete C0 controls without
  a finding and let U+FFFE through: Forensic's hex dump held one in a code block, the block fell
  back to escaped text (`bad_html`), and EPUBCheck stopped at a fatal error in that chapter.
  Replaced before the Markdown is parsed, the code block stays a code block. Forensic's EPUB,
  rebuilt from run 1's book folder, passes EPUBCheck 5.4.0 with no message.
- An EPUB that eco only optimizes can hold a page that does not parse. That page is left as it
  is, and now so is every image it refers to (the whole file name, after a quote or "/" and not
  followed by more of a name, so `1.png` is not found in `img-071.png`, while an unquoted CSS
  `url(../img/a.png)` or `b.png#part` is): renaming one to `.jpg` left the page pointing at a
  file that was gone. An `image_kept` warning names it, and the `bad_xml` finding
  says the page's links are not updated. If it turns out wrong: the X4 limits are not applied to
  such an image.

## 2026-11-18: A book.md that antivirus software removed is one plain error (R-74, R-78)

- When writing or reading `book.md` fails on Windows with errno 22 or WinError 225
  (ERROR_VIRUS_INFECTED, which Python reports as errno 22, "Invalid argument"), eco raises
  `RemovedByAntivirus`, chained from the original error. Its message says "Could not write" or
  "Could not read" and names the file, says that antivirus software may have removed it because
  the text of the book can look like malware, and says which folder can be excluded from scanning:
  for a write "eco's data folder, which holds this file", for a read "the folder that holds this
  file", since `load_source` also reads a book folder that the user passes in. It never suggests
  turning protection off.
- Once the scanner has moved the file away, a read gets "No such file" instead. Right after
  `extract_pdf` wrote the folder (a conversion of a PDF, and `eco extract`), a missing `book.md`
  gives the same plain error, "Could not find"; in a book folder that the user passes in, a
  missing file stays the usual error.
- The read is the case that happened (R-78, corrected the same day): Windows Defender let eco
  write the Malware book's `book.md` (`report.json`, written after it, exists), detected
  `Exploit:Win32/Pdfjsc.Q` (a malicious-PDF-JavaScript signature that the book's own example code
  matches) three seconds later, and the next read, in `load_source`, failed with "Invalid
  argument" after a 7306 s conversion. Both `load_source` and `eco extract` read `book.md` through
  the guard; `eco extract` reads the cached file before it copies the folder.
- A cached book folder that holds `report.json` but no `book.md` is incomplete: `extract_pdf`
  removes it and extracts again, instead of failing with "No such file" on every later run.
- Why: "Invalid argument" sent the reader to the wrong place. Whether to exclude a folder is the
  owner's decision (agent decisions Q-24).
- The acceptance harness puts the `error:` line of a failed conversion in the first line of its
  failure message. If it turns out wrong: errno 22 alone can have another cause, and the message
  only says "may".

## 2026-11-19: Numbered list items keep their numbers (R-67)

- Docling keeps a list item's marker apart from its text (`ListItem.marker`, with `enumerated`).
  When the marker is a plain number ("3." or "3)"), the block keeps that number (`Block.number`),
  book.md writes the item as a Markdown ordered-list item with it ("3. text"), and the EPUB shows
  an `<ol>` that keeps its start number. Any other numbering marker ("A.", "(i)") stays as text at
  the start of the item, which is then an item of a bullet list. A bullet is dropped as before.
- Why: every item used to be written with "- ", which lost 102 numbers in Threat Hunting (the
  review questions and answers) and the numbered steps of Malware without a finding (spec section
  5).
- A numbered item and a bullet item next to each other are separated by a blank line in book.md,
  so each starts its own list; an ordered list that does not start at 1 cannot continue a
  paragraph in Markdown. If it turns out wrong: write "- " again.
- 2026-11-19, fix round: Markdown numbers the items of one list from its first number, one by one,
  so `1. 2. 1. 2. 3.` showed 1 to 5 and `5. 7.` showed 5, 6. Now an item whose number is not the
  previous item's plus one starts a new list: book.md switches its delimiter between "." and ")"
  (`1. a`, `2. b`, `1) c`), which any CommonMark renderer reads as a new list, and the EPUB has one
  `<ol start>` for each run, so every item shows the book's number. A list may start at 0: "no
  number" is `None`, not 0. `EXTRACTOR_VERSION` is 7.

## 2026-11-19: Contents and index pages are read again from the text layer (Q-23)

- Docling labels a page of contents or an index `document_index` and reads it as a table, and its
  table model forces two columns into a grid whose rows pair entries of both columns. The adapter
  now keeps such a block as `contents`, with Docling's table, and the fix pass `rebuild_contents`
  (`src/eco/pdf/contents.py`, right after the reading order) reads it again from the PDF text
  layer inside its box: a full-width line (a part or chapter title) in its place, and between such
  lines the left column, then the right, top to bottom, one entry per line.
- In the contents each line is a paragraph without its print page number (arabic or a lowercase
  roman numeral) and its dot leader, since a reflowable book has no such pages; a line that is only
  a number stays. An index (a block in the back half of the book) keeps its numbers, which are its
  content, as one list item per line. A finding names each page read again.
- A scanned page, or a box in which the text layer has nothing, keeps Docling's table.
- Docling labelled Threat Hunting's contents pages 10-13 `document_index`, but pages 14 and 15
  `table`, with the chapter titles between them as headings; those two pages are not covered.
- If it turns out wrong: map `document_index` to a table again.
- 2026-11-19, fix round: every run left of the box's middle used to be the left column, so a
  one-column contents whose page numbers are runs of their own came out as all titles, then all
  numbers; and the last word of any line was dropped when it looked like a number ("Lab mix" lost
  "mix"). Now:
  - Lines: runs are grouped by their height on the page (a run whose middle lies within the
    tallest run of the line, or that overlaps half the lower height), so a comma whose glyph box
    sits low stays in its line.
  - Columns: the page is read in columns only where its text has a gutter: a band one line high
    that fewer lines cross than either column has, with two lines or more starting at its right
    edge and two or more left of it, the narrower column at least 0.4 of the wider. Page numbers
    and leaders start no line, so a column of page numbers is no column, and a column of labels
    beside their titles is too narrow to be one. A line that reaches into the gutter, or starts in
    the right half of the left column (a short title centred over the gutter), is full-width and
    ends the columns above it. Without a gutter the lines are read top to bottom, left to right.
  - Page numbers: a number (arabic, or a valid lowercase roman numeral) goes only when it is a run
    of its own after a gap of half its height or after a dot leader (four dots or more), or ends a
    run after a leader. Otherwise the line keeps it: a page number kept costs nothing, a title word
    lost is a failure (spec section 5). A caption of the block is a paragraph before the entries.
  - Not covered: Threat Hunting puts each chapter's number and title in the left column only, so
    its pages 11-13 read the left column of several chapters before their right column.
- 2026-11-19, fix round 2: the width ratio held a short last column of an index (three short
  lines beside six long ones) to be no column, so the entries of both columns were joined pairwise
  under a finding that said "in reading order"; it let labels beside short titles ("Chapter 1
  Introduction") count as two columns; and an italic word past the middle of the left column made
  its line full-width, taking the right-column entry beside it. The column rule is now:
  - An edge of a column is where a text run begins its line, or follows the run before it by a
    line height. An italic or code word a word space after other text is no edge, and page
    numbers and leaders make none. A run up to 2 pt left of an edge (a larger letter heading)
    starts at it.
  - An edge makes two columns when the left column spans a fifth of the page width or more;
    when two lines or more start at it, or one line level with the first line of its section (a
    last column of one line); when two lines or more lie left of it and fewer cross it; and when
    page numbers that are runs of their own do not end the right part of the lines only (then the
    left part holds labels). Of several edges, the one fewest lines cross wins, then the one most
    lines start at, then the leftmost; inside a column the same search finds a third one.
  - A line is full-width when a text run of it spans the edge, or when nothing of it lies right of
    the edge and its text reaches into the gutter or its first text run starts in the right half
    of the left column. A line with an entry in each column is never joined into one.

## 2026-11-19: Text read by OCR from a picture on a digital page is kept as the picture (Q-22)

- On a page that has a text layer, Docling also reads pictures by OCR, and their text came out as
  body text: Threat Hunting's page 192 (a picture of a sample document) gave headings that joined
  the book's outline, and pictures of tables on pages 47, 52-54 and 91 gave HTML tables built from
  OCR. The fix pass `keep_picture_text_as_images` (`src/eco/pdf/regions.py`, after the contents
  pass) keeps such text as the picture instead: a block whose centre lies in a raster picture of
  the page and most of whose words are missing from the text layer inside its box. The blocks of
  one picture become one picture block with the picture's box, which the region pass crops; a
  finding names the page.
- Both conditions are needed. A picture with a text layer over it (an OCR'd PDF, a label printed
  on a photo) keeps its text, and a page whose broken text layer Docling replaced with OCR has no
  picture under its text, so it keeps its text too.
- Scanned pages and `--ocr force` keep their OCR text, and Docling's OCR mode stays its default
  (spec section 8.3).
- If it turns out wrong: drop the pass from the fix stage.
- 2026-11-19, fix round: the picture rule is now this. A Docling picture shows a raster only when it
  covers at least 90% of the raster's box; it then grows to the whole box. Otherwise the pass adds
  a picture with the whole box, and a Docling picture that lies at least 90% inside it (a logo in
  a sample document) goes, its caption moving to the new picture. Before, a small Docling picture
  anywhere in the raster counted as showing it, so the text went and only the logo stayed. A block
  whose box holds text-layer words outside the picture keeps its text, since the crop would lose
  them. A raster inside a Form XObject gets its box on the page: PDFium leaves out the matrix of
  the form object around it, so `image_bounds` applies it (the page's image share uses it too).
- 2026-11-19, fix round 2: a block whose centre lies in a raster drawn inside a larger raster
  belongs to the larger one, whose crop shows both; a Docling picture can no longer be both grown
  for one raster and taken into another, so its caption is not written twice.

## 2026-11-19: A picture page 1 of a digital book is only the cover (T19 proposal P3)

- eco always renders page 1 as the cover image. When page 1 is a picture (no text layer) and the
  other pages of the book have a text layer, the fix pass `leave_out_the_cover_page` leaves its
  blocks out of the body: the picture and the text Docling read from it by OCR repeated the cover
  (11 words of Threat Hunting). A finding says so. A scanned book keeps its page 1, which can be
  content, and a page 1 with a text layer keeps its text.
- `EXTRACTOR_VERSION` is 6 (numbered lists, contents, picture text and this pass).
- If it turns out wrong: drop the pass; the page then shows in the body as before.

## 2026-11-19: Contents: a chapter number set apart starts a chapter zone (Q-28, M1 final review)

- On a contents page (a block in the front half of the book) read in columns, a line that holds
  only a chapter number at the left ends the columns above it, as a full-width line does. Threat
  Hunting puts each chapter's number and title in the left column only, with the chapter's
  entries in both columns below them, and its pages 10-14 read the left part of several chapters
  before their right parts. They now finish each chapter's right column before the next number.
- The number must be clearly a chapter number: alone in its line, and at least 1.25 times as high
  as the median text of the page (Threat Hunting's are 1.31 to 1.66 times as high). And every line
  whose left part is only numbers must have nothing of the right column level with it, or the rule
  is off for the whole page. The first form of the rule took any lone number and reordered two
  layouts that read right without it: a newspaper flow, whose chapter goes on at the top of the
  right column, level with an earlier chapter number; and a page number alone on its own line
  under a wrapped entry. The index (the back half) never uses the rule, since its letter headings
  sit inside a column.
- Threat Hunting's pages 10-15 and 234-240 read the same as with the first form of the rule.
- If it turns out wrong: drop `_chapter_starts`; such pages then read column by column again.

## 2026-11-19: Contents: an order inferred from the layout is a warning (M1 final review)

- The `contents_rebuilt` finding is a warning that ends "Order inferred from the layout; check this
  page." when the page was read in columns, or read as one column although a line holds text that
  follows other text by a gutter's width a fifth of the page width or more from the left edge (two
  columns that the gutter rule did not accept). A plain one-column read stays info.
- Why: every column read is inferred, and spec section 5 counts a wrong order without a warning as
  a failure. Cost: every contents or index page in columns gives a warning.

## 2026-11-19: eco writes a table's caption, and keeps it beside a table shown as an image

- `write_book` writes `Block.caption` as the table's `<caption>`, in place of any caption
  docling-core put into the HTML. docling-core 2.107 writes one although the adapter passes
  `add_caption=False`, and a version that honours the flag (docling-slim allows `<3`, and `uv tool
  install` ignores uv.lock) would have dropped every table caption.
- On an Xteink device a table with more than 4 columns becomes its twin image, which shows only the
  grid. Its caption is now the image's `figcaption`, and the footnotes after the table stay text.
  Before, both were lost (ResNet's "Table 1. Architectures for ImageNet..." on X4).

## 2026-11-19: A page is blank only when a small render of it shows no ink

- A page with no text layer and no raster image is rendered at scale 0.2 and counts as blank only
  when the render has no ink (the test `page_slices` uses). A page of vector drawing, or of text
  drawn as outlines, used to be skipped as "Blank page skipped." and never reached Docling or
  `--mode pages`. Every blank page of Threat Hunting, Forensic, Malware, ResNet and Bicara renders
  pure white, so their blank pages are unchanged.

## 2026-11-19: OCR: a page whose OCR confidence is below 0.5 is a warning (spec section 8.11)

- `extract_blocks` returns Docling's OCR score (the mean confidence of its OCR cells) for each page
  whose text came from OCR: a scanned page, or every page with `--ocr force`. The layout stage
  reports one `ocr_low_confidence` warning per page below 0.5, Docling's grade "poor", with the
  score. A page with a text layer is left out: auto OCR reads only its pictures, which stay images
  (Q-22). One finding per page, like `ocr_page`, so the report and the GUI name each page.

## 2026-11-19: PDFium's line-end hyphen marker is a hyphen in code too (R-90)

- PDFium gives a hyphen at a line end after a letter as U+FFFE (or "\x02" in a bounded text). The
  code pass kept it, and the builder replaced it with U+FFFD. The mapping table moves to `pages.py`
  and serves the contents, code and region passes.

## 2026-11-19: An image reference of a Markdown book is judged as text before any file is opened

- The builder refuses an image, cover or table-image reference with a URL scheme or host, a leading
  slash or backslash, a drive or root, or ".." that climbs out of the book folder, before it
  resolves or tests the path; the resolved path must still lie in the folder (symlinks). Why: on
  Windows, resolving `//host/share/x.png` opens an SMB connection to a host the input names, which
  sends the user's credentials during a conversion that must not use the network (spec 6.5).

## 2026-11-19: `EXTRACTOR_VERSION` is 8

- Eight commits after the bump to 7 changed what extraction writes (the round-2 fixes of Q-22 and
  Q-23, the chapter rule, the heading tie-break, the new protected short words) without a bump, so
  a book folder cached by an intermediate state was reused as complete. Version 8 also covers the
  fixes of the M1 final review: the chapter rule's guards, the contents warning, table captions in
  book.md, vector pages, OCR scores and code hyphens.
