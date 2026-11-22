# Decision log

Short dated entries. The design spec (`docs/superpowers/specs/`) holds the full reasoning.

## 2026-11-19: Docker model storage

The normal image points `ECO_MODELS` at `/opt/eco-models/models`; `/opt/eco-models` links to `/data`. The setup page can create `/data/models` even on a fresh bind mount, and downloads survive container replacement. `BAKE_MODELS=1` instead creates `/opt/eco-models/models` and downloads there for offline use. The image runs as uid 10001 and checks that `/data` is writable before starting the server.

The final local amd64 build (without baked models) measured 3,725,581,683 bytes, or 3.73 GB, with Docker's image size report. It includes CPU PyTorch and uv's copied environment. Its smoke test passed on Windows Docker Desktop. On an empty bind mount, the model path resolved to `/data/models` and created that folder successfully.

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

## 2026-11-18: Web jobs: worker process, end status, restart, upload names (M2-R4, M2-R10)

- Each job runs in a fresh `spawn` worker process; the runner thread converts one job at a time,
  first in first out. `Runner(worker=...)` defaults to `_work`, looked up when the Runner is made,
  so a test swaps `jobs._work` for a module-level fake that the spawned child imports by name.
  Cancel is `terminate()`, `join(5)`, `kill()`, `join(5)`; the worker is the base interpreter
  itself (multiprocessing skips the venv launcher, bpo-35797) and eco's conversion starts no other
  process, so nothing outlives it. If it turns out wrong: a library that starts its own process
  needs a Windows job object or a POSIX process group.
- A file that fails gets `JobFile.error` and the next file goes on. A job ends `done` if any file
  converted, else `failed`; `cancelled` only by Cancel. A worker that dies without its `end` event
  gives its unconverted files `The conversion stopped unexpectedly (exit code N).`
- When the server stops, or a new server finds a job left `running`, that job is not run again: its
  unconverted files get `The server stopped before this file was converted.` and it ends by the
  rule above. Jobs left `queued` never started, so they keep their place, oldest first. `purge`
  skips only `running` jobs. If it turns out wrong: an interrupted job is rebuilt by hand.
- Outputs are converted into the worker's `tmp/` and moved into `output/` under the upload's name
  (`output_path`, never the name of an earlier output), so `output/` never holds half a file.
- Upload names (M2-R10, plus): besides the ruling's rules, a Windows device name (`nul.pdf`) gets a
  `_` in front, because the output is named after the upload, and a name is cut to 120 characters,
  type kept, so the paths stay under Windows' 260. If it turns out wrong: an odd stored name.

## 2026-11-18: Web app guard and `eco web` (M2-R11)

- One ASGI layer, `_Guard`, sits outside all of FastAPI's own middleware (`build_middleware_stack`
  of a FastAPI subclass), so it runs before routing and every response passes it, the 500 of an
  unhandled error too. It sets CSP, nosniff and no-referrer on every response.
- Local mode (no token): a request must be addressed to `127.0.0.1`, `localhost` or `[::1]` with
  the port the server listens on (the ASGI `server` address; no port only when that is 80), else
  403. This stops DNS rebinding. Network mode (a token): `Authorization: Bearer` or the
  `eco_token` cookie, compared as bytes with `hmac.compare_digest`, else 401 on every path;
  `GET /?token=` sets an `HttpOnly; SameSite=Strict; Path=/` session cookie and redirects to `/`.
  Both modes refuse a POST, PUT, PATCH or DELETE whose `Origin` is not `<scheme>://<Host>`: 403.
  If it turns out wrong: a reverse proxy in front of a loopback server must use network mode.
- `eco web` treats only `127.0.0.1`, `localhost` and `::1` as this computer. Any other `--host`,
  `127.0.0.2` too, gets a token (`--token`, else `ECO_TOKEN`, else `secrets.token_urlsafe(24)`).
  For `0.0.0.0` and `::` the browser opens at `127.0.0.1` or `[::1]`, which a browser can reach;
  it opens after 1 s so the server already listens, and not at all if the server stopped first.
- FastAPI's `/docs`, `/redoc` and `/openapi.json` are off: their pages load scripts from a CDN.

## 2026-11-18: One server per data folder; no framing (M2-R12, M2-R13)

- uvicorn runs the app's startup before it binds the port, so a second `eco web` on the same data
  folder used to run `purge()` and `runner.start()` before it failed, and settled the first
  server's running job as stopped. Now `server_lock(data)` holds an OS lock on
  `<data>/jobs/server.lock` (msvcrt on Windows, flock elsewhere; it ends with the process, so a
  crash leaves no stale lock). The app's lifespan holds it around purge, start and the whole run;
  `eco web` tries it first, so a second server prints `error: Another eco web is already using
  <data>` and exits 1 before it starts. Two `eco web` started at the same instant: the loser
  passes the first try and its lifespan fails (uvicorn's startup error, exit 3), still before it
  touches a job. Only a held lock gives that message; any other lock error is shown as it is.
  If it turns out wrong: a file system without locks (some network shares) stops `eco web` with
  the OS's error.
- Every response also carries `X-Frame-Options: DENY`, so no other site can frame the app. The
  plan's CSP string stays exactly as it is.

## 2026-11-18: The guard refuses websockets; `eco web` tokens are strong (M2-R14)

- `_Guard` lets only `lifespan` and `http` scopes reach the app. A `websocket` scope is closed
  with code 1008 before any route, whatever its Host or token: the GUI uses SSE, and a websocket
  route would otherwise skip the Host, token and Origin checks. Any other scope type is dropped.
  If a later task wants a websocket: give it the same checks in the guard first.
- A token given to `eco web` (`--token` or `ECO_TOKEN`, local or network mode) must be at least 16
  characters, each one of `A-Z a-z 0-9 - _`. Otherwise `eco web` prints `error: The token must
  be at least 16 characters, each one of A-Z, a-z, 0-9, - or _.` and exits 2 before it makes the
  data folder. An empty value still means no token. Such a token is URL-safe as it is, so the
  printed `?token=` needs no quoting, and it is ASCII, so a Bearer header carries it (Starlette
  reads headers as latin-1). `create_app` itself takes any token. There is no rate limit on 401;
  16 characters of that alphabet are what keeps an online guess from the LAN out of reach.
  A token that starts with `-` must be written `--token=-...` (argparse).

## 2026-11-18: Jobs API: streamed uploads, one error shape, no paths of the server (M2-R15)

- An upload is read with python-multipart's own parser (`_Upload`), and each file is written, as it
  arrives, into a folder that `JobStore.reserve()` made. Starlette's form parser is not used: it
  writes every file to a temporary file before the route runs, so a limit could only be checked
  after the whole upload was on the disk. The limit (`--max-upload-mb`; 1 MB is 1 MiB) is for all
  the files of a request together, and it is checked before each write, so the disk never holds a
  byte over it. A `Content-Length` of more than the limit plus 1 MiB (what framing and the options
  may take) is refused with 413 before the body is read. A body that goes over the limit, or over
  that sum with other parts, while it arrives is refused at that moment, and the folder is
  deleted. A folder without a job.json (the server died in the middle) is no job, and the next
  start removes it (M2-R18). If it turns out wrong: a client whose framing is over 1 MiB is
  refused; raise `_OVERHEAD`.
- The type check is by suffix and case does not matter. The 400 message names the file as it was
  uploaded. The `options` field is JSON, before or after the files. An unknown key, a value of the
  wrong kind, or a `font_size` that is not a whole number from 8 to 96 is 422 (`font_size` goes
  into Typst source, and `Options` does not check it); a device or the like that does not exist
  gives the message of `Options`. Nothing posted gives the defaults, and a blank title, author or
  language is not set. The `options` of a job as the API shows it can be posted back as they are.
- No path of the server leaves through the API. A job shows names, indexes, sizes, options,
  positions and errors. A file's `outputs` (format to name) and `sizes` (format to bytes) are what
  its `file` event shows too, so the page reads both the same way; the event has no `book_dir`.
  In an error text the data folder is `<data>`. A path outside the data folder in an error text
  is not cut out. If it turns out wrong: a path leaks that way, cut it in `_scrubber`.
- Every error is `{"error": "<plain English>"}`: FastAPI's own 404, 405 and 422, and a 500 too.
  Cancel answers 202 with the job, or 409 when the job has finished. A rebuild takes the options as
  JSON (none means the defaults) and answers 201 with the new job. A download has a
  `Content-Disposition` with the name in ASCII and in UTF-8 (M2-R19); `{n}` is a plain decimal
  index, `{fmt}` is only looked up in the job's outputs, and the file must lie in the job's
  `output/` folder.
- An event stream subscribes in its own generator and unsubscribes in `finally`, so a client that
  goes, a job that never ends and a response that the server cancels leave no queue behind. It
  looks at its queue every 50 ms: the queue is the runner thread's. It also ends when the server
  is asked to stop (M2-R16).

## 2026-11-18: Prompt shutdown, file cap, hourly expiry, download name fallback (M2-R16 to M2-R19)

- M2-R16: uvicorn waits for the responses in flight before it stops, and an event stream does not
  end by itself, so Ctrl+C during a conversion with the page open needed a second Ctrl+C (measured:
  a server with a stream open was still running 12 s after `should_exit`). `eco web` now runs
  `eco.web.app.Server`, a `uvicorn.Server` whose `handle_exit` sets `app.state.stopping` (a
  `threading.Event` that `create_app` makes) and then does what uvicorn does. Every event stream
  looks at the flag at each of its looks and ends, with no `end` event because the job has not
  ended; a browser that reconnects finds no server. `timeout_graceful_shutdown=5` is the backstop
  for what the flag does not end, an upload or a download in flight: after 5 s uvicorn cancels it
  (and logs it). One Ctrl+C measured: the real `eco web` with a stream open stopped in 0.2 s, exit
  code 0, nothing on stderr. If it turns out wrong: a second Ctrl+C still forces the stop, as
  before.
- M2-R17 (a product decision: the spec sets only the size limit): at most `MAX_FILES = 200` files
  in one upload request. The 201st file part is refused with 400 `Too many files (limit 200)` as
  its headers end, before a byte of it is written, and nothing of the request stays. Without a
  cap a request of 500 MB could make millions of empty files in one job folder. If it turns out
  wrong: raise the constant.
- M2-R18: the spec says a job older than 7 days is deleted by itself, and `purge` ran only at the
  start, so a server that runs for weeks never expired a job. At start (the lock held, before
  `runner.start()`) `purge(orphans=True)` also removes a folder without a readable job.json
  whatever its age: no request is in flight yet, so it is an upload that a hard kill cut. Then,
  once in `PURGE_EVERY` (an hour), `purge(keep_queued=True)` runs while the server does. It leaves
  the queued jobs (the runner has them in its queue) and the running ones (their worker uses the
  folder), and a folder without job.json goes by its age, so an upload that is coming in stays.
  It is a task of the lifespan (`anyio`), on a thread, off the event loop. It stops with the
  lifespan, and it does not change the runner. A timer in the runner's thread would not have run
  while a conversion runs, and that can be hours. A purge that fails is logged and the next one
  tries again. If it turns out wrong: a job that has run for more than 7 days is removed within
  an hour after it ends, because it is older than that by then.
- M2-R19: a download has `Content-Disposition: attachment; filename="<ascii>";
  filename*=UTF-8''<percent-encoded>`. In the ASCII name each non-ASCII character, `"`, `\` and
  control character is `_` (RFC 6266, section 4.3), for a client that does not read `filename*`
  (curl's `-J` reads only `filename`). An event stream sends the comment `: keepalive` after 15 s
  with no event, so a proxy does not close it for being idle and a server that follows ASGI spec
  2.4 finds a client that has gone. A browser ignores a comment.

## 2026-11-18: Preview API (M2-R20 to M2-R27, M2-R32)

The rulings fix the routes, the caches (`<job>/preview/<n>/`), the numbering (pages from 1, chapters
from 0) and the state (409 before the conversion). These are the choices they leave open.

- A source page is drawn 600 px wide and at most 6,000 px tall. A page 1 pt wide and 14,400 pt tall
  would be 8,640,000 px tall at 600 px wide, and PDFium refuses a bitmap that size; such a page is
  drawn smaller. "At most 10 times as tall as it is wide" cannot hold for it at any scale, so it is
  read as 10 times the 600 px. If it turns out wrong: two constants, `SOURCE_WIDTH` and
  `SOURCE_MAX_HEIGHT`.
- A book with no `#` heading is chapter 0 of the live preview, though its `chapters` list is empty
  (M2-R26 calls it one chapter, and without this it would have no chapter to ask for). Text before
  the first `#` is no chapter: `chapter=0` is the chapter of the first heading. `X-Excerpt-Index`
  counts from 0 (the page of the excerpt) and `X-Excerpt-Pages` is the number of pages of the
  excerpt.
- Statuses the rulings leave open. An unknown `size` is 400 `Unknown size: <s>`, like a view and a
  format. A `font_size` outside 8 to 96 is 422 with the text of the upload options. A `page` of a
  file that is not a PDF is 404 like `source`; a `page` the PDF does not have is 404 `No such
  page`, `page=0` too. A PDF that cannot be read is 422 `This PDF could not be read`. A file whose
  book cannot be found or built (a reflow PDF whose extraction folder is gone, an EPUB that cannot
  be read) is 404 `No preview is available for this file`, and for its text `This file has no text
  to show`. A request is checked in this order: job, file, the values it gives (400, 422), the
  state (409), then the page or chapter (404).
- The text route sends the book as the file holds it: the uploaded Markdown, or the `book.md` of an
  EPUB's book folder or of a reflow PDF's. It has its front matter, and CRLF line endings where
  `write_book` wrote it on Windows (text mode), and no size limit. The page shows it with
  `textContent`. If it turns out wrong: cut it at a length, or drop the front matter, in the route.
- PDFium is not thread-safe, and the routes run on a pool of threads, so every use of PDFium in the
  server process (the page count, a source page, the page book of a pages-mode PDF) holds one lock.
  The page book of a long pages-mode PDF therefore makes the source pages wait.
- An image of more than `Image.MAX_IMAGE_PIXELS` pixels (89.5 million) is left out of a preview,
  like an unreadable one. PIL refuses only more than twice that, and for the sizes between it warns
  and decodes the picture whole; an EPUB's images are copied as they are, and a PNG of 90 million
  pixels takes 400 KB. The check is in `md2typst`, on the header, before any decoding.
- The routes send no cache headers. The live preview keeps its last 32 answers on the server, and a
  page that the browser asks for again is a small file.

## 2026-11-18: Uploads keep their own name on disk (M2-R36)

- An upload is stored as `<job>/input/<n>/<name>`: a folder for each file number, and the file in
  it under its own name (`safe_name`, M2-R10). It was `input/<n>-<name>`. M1 takes names from the
  path it reads: a PDF that has no title of its own, and a Markdown file that has none in its front
  matter, get `path.stem` as their title, and `epub_to_book` writes the file name as the `source`
  of the book it makes. So `book.md` became an EPUB titled `0-book`, which the e-reader's library
  shows, and the text of an EPUB in the preview said `0-name.epub`. The output names were right
  already (`_work` names them after the upload, never like an earlier output).
- A folder for each file also keeps two uploads with one name apart, as the prefix did. The layout
  is one function, `input_path(inputs, n, name)`, used by `JobStore.create`, `adopt` (for the files
  that `_Upload` wrote there) and `rebuild`. `rebuild` links by number and the name the job shows,
  so it does not read the path of the old job: a job of the old layout can still be rebuilt, and
  its rebuild has the new one. Nothing moves a job folder of the old layout, since M2 is not
  released. `purge`, the orphan rule at start and the cap of 200 files are as they were.
- `safe_name`'s rule for a Windows device name (`nul.pdf` gets a `_`) is now the only guard of the
  stored name: the `<n>-` that came first used to be one as well. If it turns out wrong: a name that
  the rule does not know (`COM¹`, `CONIN$`) is stored as it is.

## 2026-11-18: Model setup API (M2-R28 to M2-R31)

- `POST /api/setup/download` takes an optional `{"ipv4": true}` (the page's retry, as `eco setup
  --ipv4`); any other key or a non-boolean is 422. The download runs on one daemon thread, so Ctrl+C
  does not wait for it and finished files resume on the next run. The start and the "already
  running" check are one step under a lock, so two POSTs at once start one run (the other is 409).
- The event stream replays the whole last run to a reader that joins late, then goes live, and ends
  after `end`; the log of a run stays until the next POST. With no run since the server started it is
  404. Progress lines are the `eco.models` logger's (one per retry) plus one start line: there is no
  percentage, because `download_models` reports none. The `end` message of a failure is the error's
  text with the data folder cut out; M1's text ends with "run eco setup again", which is the CLI's
  advice and still true.
- A POST is accepted when the models are already ready (it runs the downloader again, which checks the
  files and repairs a damaged one); the page offers the button only when they are missing.
- The code is in `eco.web.models_setup`, not `setup.py` (tools treat that name as a packaging script).

## 2026-11-18: The workspace page (Task 9, M2-R34, M2-R35)

What the page does where the rulings leave a choice. Vanilla HTML, CSS and JavaScript, no build step;
the texts are in `strings.py`.

- The setup gate is the first screen only when the address holds no job. A job in the address
  (`#job=`) opens at once, since a finished job needs no model. The gate hides the stepper and
  replaces Select files completely, so Markdown and EPUB files wait for the models too, as the brief's
  "gate" says (M2-R39, below, adds a way past it). A reload in the middle of a download shows the
  button again; a click gets 409 and opens the stream, which replays the log.
- The stepper: Select files and Settings are links once they are done (to the start). Processing is
  not a link when it is done: a finished job opens Review (M2-R34), so there is nowhere to go back to.
- A file that is not `.pdf`, `.md` or `.epub` is refused when it is added, with the server's text
  (`Unsupported file type: <name>`), so no upload starts for it. The server's 400 stays the backstop and
  is shown the same way, under the drop zone, as is any other upload error (413, 200 files).
- Processing lists only the stages a file goes through: a PDF has Reading PDF, Recognizing page layout,
  Fixing code, formulas and reading order, Building EPUB and Optimizing and compressing (page images
  skip Fixing), a Markdown file has the last two, an EPUB the last. `Creating XTC` is added only when
  XTC is asked for. A stage that sent no event because the PDF was read before (the extraction cache)
  is shown as done, with "already done", as soon as a later stage starts.
- The bar is the share of stages done, plus the share of pages while the layout stage runs. The time left
  comes from the page rate, measured between live page events at least 0.5 s apart and averaged. The
  events of a replay (a reload) only move the starting point: they arrive within a moment, and their rate
  would be absurd. So there is no estimate before the second live page event.
- The feed in Processing shows the findings of the file being converted; Review shows those of the file
  selected. A finding with no source page is plain text, not a button. With several files, Review has a
  file select, and the chips, download and previews follow it. A file that was not converted shows its
  error. When no file converted (failed, cancelled, stopped by a restart), the one primary button is
  `Try again`, which rebuilds with the job's own options.
- `Apply changes` is a secondary button, so Review keeps one primary button, `Download EPUB`. The panel
  starts at the job's own values and shows the page as converted; the live picture appears after the first
  change, and returning to the job's values shows the stored page again. The live picture of a PDF is the
  source page being shown; for Markdown and EPUB it is the first page of the chapter that holds the page
  being viewed (the API gives no other page of a chapter), and its caption says "page X of Y of this
  chapter". The picture of a request is shown as a `data:` URL, since CSP allows no other for a fetched
  image.
- "View as" starts from the firmware the job was made for (Not sure and CrossPoint: CrossPoint; CrossInk;
  Stock). Changing it asks for the pages again and keeps the place: the same source page, or the chapter's
  first page.
- The font size is a preview setting in M2 (the EPUB is not changed by it), and its hint says so. M3 adds
  the XTC page style to the same panel.
- A stream that ends without `end` shows "The eco server stopped" and is not reopened: a browser would
  reconnect and replay the whole log. After a restart the user reloads, and the job shows as stopped.
- Colours. The success, warning and error tokens are 2.1 to 3.6 : 1 on white and the border token is
  1.5 : 1, too weak for text and for the edge of a control. Text uses `#1a7f37`, `#8a4b00` and
  `#d70015`, control edges `#86868b`, and accent text and the hover of the primary button `#0062c4`
  (white on `#0077ed` is 4.3 : 1). The tokens of DESIGN.md stay for fills and decoration. Steps and chips
  use the control radius, not pills.
- `create_app` sets the type of `.js` to `text/javascript`: StaticFiles asks the system, and
  `/etc/mime.types` or the Windows registry may say `application/javascript`.
- The page has an empty `data:` icon, so the browser does not ask for `/favicon.ico` and log a 404 on
  every load.
- Not done: remembering the settings between visits, an upload progress bar, a chapter picker, and a
  reconnect after a restart.

## 2026-11-18: Continue without the models (M2-R39)

- Spec §8.14 asks the setup page to list the models with their sizes and total, to ask for consent, and
  to say clearly at conversion when the models are missing. It does not block an input that needs no
  model. Markdown and EPUB files need none, and neither does a PDF read as page images, so a 417 MB
  download must not be the price of converting them.
- The setup gate is still the first view while `/api/setup` is not ready and the address holds no job.
  It has a second, secondary button, `Continue without models`, beside the primary `Download models
  (~417 MB)`. The button opens Select files for this page load only. The page keeps a flag in memory,
  so a reload shows the gate again, and until then every return to the start (the stepper links, a bad
  address) goes to Select files.
- While the models are missing, Select files shows one muted line, `Without the AI models, PDFs
  convert only with Layout set to Page images.`, and a secondary `Download models` button that goes
  back to the gate, where the sizes and the consent are. The line goes when a download that was started
  finishes, also when the user left the gate while it ran. (M2-R41, below, gives the line two more
  texts: a download is running, and a download failed.)
- Markdown, EPUB and Page images PDFs convert as usual. A PDF in another layout mode starts, then ends
  `failed` with the message the server already gives (`AI models are not installed. Run: eco setup`).
  There is no check at upload and no server change. (M2-R43, below, adds a warning on the row of a
  PDF, which the page works out from the Layout alone.)
- The gate keeps what a download made of it (a running download, a failure, the log) while the user is
  on Select files. Showing the gate no longer resets its buttons: that let the first button start a
  second download, and it lost a failure that came while the gate was hidden.
- This replaces the sentence of "The workspace page" that made Markdown and EPUB files wait for the
  models. If it turns out wrong: remove the one button, the one line and the one control.

## 2026-11-18: File rows show pages, scan state and an estimate (M2-R41, M2-R43)

Spec 8.13 item 1 asks each file of Select files to show its page count, whether it is digital or
scanned, and an estimated time. The plan cut the rows to a name and a size. This adds the rest, through
a new route.

- `POST /api/inspect` takes one PDF in the field `file` and answers `{"pages", "scanned_pages",
  "seconds_per_page": {"digital", "scanned", "pages"}}`. The upload is the job upload's: streamed to
  disk by `_PdfUpload` (a subclass of `_Upload` that takes one `.pdf` in the field `file`), with the
  same limit and 413 text, the refusal by `Content-Length` before the body is read, and the same name
  rule. A file that is not a PDF is 400 `Only PDF files can be inspected`, a second file is 400 `Too
  many files (limit 1)`, and a PDF that M1 cannot open (damaged, password-protected) is 400 with M1's
  own message (`Not a readable PDF: <name>`, `PDF is password-protected: <name>`).
- The PDF is stored in a reserved job folder (`JobStore.reserve()`), which is no job: it has no
  job.json, so a server that is killed in the middle leaves what the orphan purge at the next start
  removes. The folder is deleted before the answer, on success and on every error. `describe_pdf` in
  `preview.py` reads it with M1's `inspect_pdf()` under the same `_PDFIUM` lock as the previews, since
  PDFium is not thread-safe. `scanned_pages` counts `PageInfo.is_scanned`, the rule the `read` stage
  of the pipeline uses. A generated PDF of 801 text pages took 1.6 s to read on this computer.
- The rates are `SECONDS_PER_PAGE` in `preview.py`: digital 0.7, scanned 2.1 and page images 0.2
  seconds a page. Provisional. The first two are the PDF engine spike on the owner's M3 Mac (Docling:
  8 to 10 s for 13 digital pages and 27 s for 13 scanned ones); page images have not been measured.
  The acceptance run recalibrates all three. The server owns them, so a new calibration changes no
  file of the page.
- The page works the estimate out from the answer and the current settings, the way the pipeline will
  run: page images (Layout set to Page images) cost pages x the page-image rate; otherwise OCR off costs
  pages x digital, `Every page` costs pages x scanned, and `Automatic` costs the digital pages at the
  digital rate and the scanned ones at the scanned rate. It is worked out again when Device, Layout or
  OCR changes. The pipeline chooses page images by the Layout alone, and the device only sets the
  screen the images are cut to, so the device has no term yet; its listener is there so that one
  needs no change of the page. Under 45 s the row says `under a minute`, else `about 6 min`.
- The words. `<size> · <n> pages · Digital PDF · about 6 min`. A PDF with most of its pages scanned (more
  than half) says `Scanned, uses OCR`, or `Scanned, no OCR` when OCR will not run (OCR off, or Layout set
  to Page images); one with fewer says `Partly scanned (3 of 40 pages)`. Markdown and EPUB rows show
  `<size> · Markdown` or `<size> · EPUB`: they have no pages and convert in seconds, so they are not
  read.
- One PDF at a time. The page sends the PDFs to the route in a queue and never beside the upload of the
  job: Start stops a reading in progress, and the PDF is read again if the job's upload fails. Removing a
  file aborts its request. A row that waits or is being read says `Reading…`. An answer, a new setting
  and the end of a download change only the text of the rows, never the rows, so a Remove button that has
  the keyboard focus keeps it. An error shows in the row as a muted warning with the server's text; the
  file stays in the list, and Start stays enabled, since the conversion reports the same error.
- Known cost: each PDF travels twice, once to be read and once with the job. On this computer both go
  to the same disk, and the first copy is deleted at once. The later fix is to stage uploads: keep the
  file from the first transfer and let the job point at it. That needs a store of staged uploads, the
  rule for when an unused one expires, and a purge, so it is not done here.
- M2-R43 (extends M2-R39). While `/api/setup` says the models are not ready and the Layout is not Page
  images (the pipeline sends a PDF to page images only for that Layout), the row of a PDF shows a muted
  `Needs the AI models. Download them, or set Layout to Page images.` in place of the estimate. It goes
  back to the estimate when the models become ready or the Layout is Page images. Review is unchanged.
  The page still has no server check: a PDF whose extraction is already in the cache would convert
  without the models, and its row warns all the same.
- The note of Select files (M2-R39) has three texts, by what became of the download this page started:
  the models are missing (the default), a download is running, and a download did not finish. Before,
  the failure went into the hidden gate and the note read the same in all three cases. The note is a
  status region, so a screen reader hears the change. When the models become ready while the keyboard
  focus is on `Download models`, the focus moves to the heading of Select files before the note goes.
  A page that is reloaded in the middle of a download still shows the first text, since `/api/setup` has
  no `running` key.

## 2026-11-18: Preview and EPUB rules: line-start markup, 1 GiB cap, page starts, image size (M2-R2, M2-R5, M2-R8, M2-R9)

- Line-start markup (M2-R2). The Typst writer escapes more than the special characters: a text line
  that starts with `<digits>.`, `-`, `+` or `=` gets a backslash, so "1. Introduction" in book.md
  shows as text and not as a numbered list item (`/` is escaped everywhere, as are the other special
  characters). Spec section 5 allows no content to change without a warning. If it turns out wrong:
  a few extra backslashes in the Typst source.
- EPUB size cap (M2-R5). An EPUB whose entries add up to more than 1 GiB (`MAX_EPUB_BYTES`) when
  unpacked is refused, by the optimizer and by `epub_to_book` (so by the CLI and the GUI) with
  `EPUB expands to more than 1 GiB: <name>`. The sizes come from the zip directory and the check
  runs before any entry is read, so a zip bomb never unpacks. The CLI prints it as one error line; the
  GUI shows it as the file's error. It had to be there before the GUI took uploads (spec sections
  6.5 and 8.13). If it turns out wrong: a legitimate giant EPUB is refused with a clear message; raise
  the constant.
- Page starts (M2-R8). Only a top-level `#` heading starts a preview page and gets a `<chap>` marker,
  like the EPUB builder, which makes chapters from top-level h1 only. A `#` inside a blockquote or a
  list item is an ordinary level-2 heading with no page break, since a page break cannot sit inside a
  quote and one valid Markdown line must not break the whole render. If it turns out wrong: such
  headings look like level-2 headings in previews.
- Image size in previews (M2-R9). An image renders at most at its natural pixel size (1 px is 1 pt)
  and at most the body width, never enlarged, as in the M1 never-upscale rule. With a caption, the
  image height is capped so that the image and its caption fit on one page body (a floor of a
  quarter of the body height). The plan's `image(width: 100%, fit: "contain")` clipped captions under
  tall images, which loses content, and enlarged 40x30 px formula crops to the full width. If it turns
  out wrong: previews show smaller images than a reader that scales them up.

## 2026-11-18: Delete a conversion, bounded tables in previews, sturdier jobs (M2-R45 and the final review)

- Delete by hand (M2-R45; spec section 8.13 "dan bisa juga dihapus manual", section 6.5). A `DELETE`
  of `/api/jobs/{id}` removes a job that has ended (done, failed, cancelled): 204. A queued or
  running job is 409 "This conversion has not finished. Cancel it before you delete it."; no such
  job is 404. job.json goes first, under the store's lock, so the job leaves every route at once;
  then the folder, tried again for about 1.5 s on Windows. What still will not go is a folder
  without job.json, which the next start purges. A preview that races the delete (or the 7-day
  purge) must not make the job's folder again: preview folders are made one level at a time inside
  the job's folder, `render_book` makes nothing above its cache folder, and a book that M1 builds
  (an EPUB, a pages-mode PDF) is built in a reserved folder of its own and moved into the job by a
  rename, which fails when the job is gone. Whatever fails while the job goes answers 404 "No such
  job". Review has a secondary "Delete conversion" button: a `window.confirm` first, then Select
  files, which reads Recent conversions again; a failure shows the server's text, and a job already
  gone counts as deleted. Why: "manual" in a GUI means a control, and a private document should not
  wait 7 days. If it turns out wrong: one route and one button to remove.
- Tables in previews (final review, Important 1). A colspan is cut to 1..1000 and a rowspan to the
  rows left (0 runs to the end), the way browsers read them; the columns come from a walk of the
  grid that respects rowspans, and each row is filled to the width where it really ends. A colspan
  stops before a column that a rowspan above takes, since Typst refuses overlapping cells and one
  sloppy table stopped the whole preview. Beyond the review's fix: a table of more than 20,000
  places (rows times columns) shows its image twin, or a box "Table too large to preview". Typst
  pays for every place that holds a cell, an empty one too: after the cut, 20 KB of HTML (one
  colspan of 1000 above 1000 short rows) still took 94 s and 6.3 GB, while 20,000 places take 2 to 3
  s and at most 260 MB. The EPUB keeps the table. If it turns out wrong: a real table of more than
  20,000 places shows the box in the preview; raise `_MAX_TABLE_PLACES`.
- job.json (final review, Minor 3; Task 4 minors). It is flushed to the disk before the rename, and
  on Windows the rename is tried again for about 1.5 s while an antivirus or the indexer holds the
  file. A save that fails after the `end` event writes no second `end`: the next try, or the next
  start, only saves job.json with the status that the `end` gave. The start purge removes at once
  only a folder with no job.json at all; a job.json that is there but cannot be read (another
  version of eco, a power loss) goes by the 7-day age rule, so one schema change cannot delete every
  job.
- Stored names (final review, Minor 2). `safe_name` also marks COM0, LPT0, COM and LPT with the
  superscript digits 1 to 3, CONIN$, CONOUT$ and a device name with spaces before the dot, and it
  cuts a long name to 200 bytes of UTF-8 (the `_` included), at a character, keeping the type. 120
  characters of CJK or emoji were up to 480 bytes, and Linux and macOS take 255.
- The worker (final review, Minor 1). Every worker starts through `_worker_main`, which ignores
  SIGINT (the console's Ctrl+C reached the worker, which failed the job with "exit code 1" and a
  traceback, against M2-R16) and starts a thread that waits for the server's process and ends the
  worker when it goes (a killed server left its worker running, to hang later on a full pipe of
  events). It is a wrapper for every worker rather than lines in `_work`, so the tests' stand-in
  workers run it too and the tests can see it work.
- `eco web` on the any-address (`0.0.0.0`, `::`) prints the loopback address that this computer
  opens and the line "On another device, use this computer's network address in place of 127.0.0.1."
  (no device can open `0.0.0.0`). `--max-upload-mb` takes a whole number above 0 only.

## 2026-11-18: The renderer honours the page style: bar, boxes, orientation (M3 Task 2, M3-R3, M3-R9, M3-R10, M3-R11)

`render_book`, `render_chapter` and `to_typst` take a `PageStyle` and `RenderSettings` is gone. These are
the choices the rulings and the spec leave open.

- Text as written (M3-R10). A `-` before a number (Typst makes a minus sign U+2212 of it, also before a
  superscript or an Arabic-Indic digit) and `...` (an ellipsis) are escaped like `--`, `---` and `-?`
  were, and `smartquote` is off, so quotes stay as typed. A dot is escaped when two more follow it, so
  no run of dots is left with three. A `-` or a `.` that ends a piece of text is always escaped: a
  link's text is escaped on its own, and what follows a piece could join it (`a -[5](#n)` was a minus
  sign). An XTC page is the book's text as a picture, and a changed
  character would be content that changed without a warning (spec section 5). If it turns out wrong:
  straight quotes look less typographic; one regex and one `set` rule.
- Strings in the source (M3-R9). The font family, the language and the chapter titles (the `<chap>`
  markers, which the bar reads as data) go through `_str`, and the weight is written as `int(...)`, so
  a style built in code (only `from_json` checks a weight) cannot put anything else into the source.
  `lang: auto` takes the book's language when its first subtag is two or three lowercase letters, and
  "en" (Typst's default) otherwise.
- The progress bar takes `bar_font_size + 2 * bar_edge_margin` px at its edge, and `margin` more lies
  between it and the text; with the bar off nothing is kept (M2 kept 22 px with its status bar off).
  That is the least (M3-R11): with a line the text starts 4 px inside the edge margin, so the side
  that the line is on takes `max(bar_edge_margin, 4)`, and the area always holds all that is drawn.
  From the edge inwards: the edge margin, the line (2 px; the read part black, the rest light gray 170,
  a level XTH has), its chapter ticks (6 px, black, reaching 2 px past the line on both sides, at the
  first page of each chapter but page 1), and the row of text, which starts at the edge margin when
  there is no line. `bar_side_margin` is the distance of the text and the line from the sides of the
  page, not from the text margin (both are 16 by default), and `bar_full_width` runs the line from side
  to side. The row is one string, left-aligned: title, `x / y`, book percent, chapter `x / y`, chapter
  percent, joined by two spaces, a middle dot and two spaces. A title that does not fit is cut at a
  character, so that the numbers stay. Numbers that do not fit the row are left out from the end,
  whole (half of one would read as another), and a first number that alone does not fit is left out
  too: the row is one line inside its own area, never wrapped over the page. Text before the first
  heading counts as a chapter with no title.
  It is a `footer` (`header` at the top) with a descent of 0, and `place` puts each part. If it turns out
  wrong: the geometry is in `_bar`.
- Image boxes. `#show image` wraps each image in a `box` with a `<imgbox>` marker (`here().position()`
  and `measure`). Without the box a figure whose caption is wider than the image reports the start of
  the line that the image is centered in, 31 px to the left in a test. An image of relative width (a
  vector image) measures 0 wide alone, so it is measured at the width of its container, which
  `layout` gives inside a `place` (a quote or a list takes some of the body's width, and the box is
  its frame). A box takes every pixel the image touches, so an image between
  pixels has a box 1 px bigger. The stock view's placeholder, a table that is too large and the text
  have no box. The boxes are kept in `map.json`, and a cache without them is rendered again.
- Orientation. A page is laid out with its width and height swapped for 90 and 270 and then turned
  clockwise (PIL `transpose`, no resampling), and its boxes are turned with it. EPUB previews are never
  turned: M3-R3 lists the style fields that simulate and an EPUB has no orientation.
- Preview caches are `<format>-<view>-<style>`, the style being the first 12 hex digits of the SHA-256
  of its JSON with sorted keys, so two styles never share a folder and the folder of an M2 job's old
  pages (`epub-crosspoint-32`, another font) is not read again.
- An SVG that Typst cannot read (width and height 0, for one) fails the whole compile, and without an
  image profile nothing else reads it: each SVG is compiled alone on a 10 pt page first, and the
  verdict is kept by the SHA-256 of its bytes. One that fails is left out like any image that cannot
  be read.
- Hyphenation (spec section 8.9, "check for `id`"): Typst 0.15 has no Indonesian patterns. With `lang`
  `id`, `ind` or `ms` the `hyphenate` switch changes nothing, and English, German and Dutch hyphenate.

## 2026-11-18: A missing Visual C++ runtime is named, and the page does not suggest IPv4 (M3-N3, Q-20)

On a clean Windows machine the PDF engine cannot load without the Microsoft Visual C++ Redistributable.
On the owner's laptop the model download ended with "could not find or load spatialindex_c-64.dll"
(rtree loads before PyTorch, so PyTorch's own hint never showed), and the page offered "Try again over
IPv4", which failed the same way. Spec section 5 lists a fragile install on Windows as an anti-goal, and
section 8.14 asks for a clear message.

- `eco.models.vc_runtime_missing(e)` says whether an error means that. It is true only on Windows, and
  only for these forms, in the error or in any error it was raised from (`__cause__`, `__context__`):
  an `OSError` whose message holds "could not find or load" and ".dll" (rtree); an `OSError` with
  `winerror` 126, or a message holding "Error loading" and ".dll" (PyTorch); an `ImportError` whose
  message holds "DLL load failed" (onnxruntime and other extension modules).
- Such an error becomes `VcRuntimeMissing`, raised from the original, with one message: "The Microsoft
  Visual C++ Redistributable (x64) is missing. Install it from
  https://aka.ms/vs/17/release/vc_redist.x64.exe and try again." `download_models` raises it at once,
  with no retry and no `--ipv4` hint. `extract_blocks` raises it for anything that goes wrong while it
  imports and runs Docling, because the DLLs load at different steps. So `eco setup`, `eco convert`,
  `eco extract`, the GUI download and the GUI jobs each show that text where they show any error.
- The `end` event of a GUI download that stopped this way has `"vc_runtime_missing": true`; no other
  `end` event has the key. The page then shows the message alone, with no "Try again over IPv4" and no
  IPv4 hint. "Try again" stays, for after the install.
- eco does not look for the runtime when it starts. It names the failure where it happens, so on
  Windows a DLL that fails to load in these forms gets this message whichever DLL it was. The original
  error stays chained. If it turns out wrong: the forms are in one function.

## 2026-11-19: XTC device behavior awaits owner verification (M3 Task 8)

The container writes one-based chapter page numbers while eco's internal `Chapter` values remain
zero-based. `XTH_VALUES` currently maps the four displayed levels using the CrossPoint layout proven
by the codec vectors. Both choices still need a real-device check; `docs/device-check.md` is the
repeatable procedure.

| Firmware and version | Gray order | Chapter jumps | CSS and images | Large chapter | Result |
| --- | --- | --- | --- | --- | --- |
| CrossPoint (record version) | Not checked | Not checked | Not checked | Not checked | Pending owner check |
| CrossInk (record version) | Not checked | Not checked | Not checked | Not checked | Pending owner check |

Record the large chapter's load time in its column. If light and dark gray are reversed, exchange the
85 and 170 mappings in `XTH_VALUES`, regenerate the kit, rerun the tests, and repeat this check.
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
  - Not covered by this round: Threat Hunting puts each chapter's number and title in the left
    column only, so its pages 11-13 read the left column of several chapters before their right
    column. The chapter rule covers it since ("a chapter number set apart", below).
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

## 2026-11-19: Headings: an equal bookmark match goes to the nearer page; more short words kept

- When two headings on the pages around a bookmark match its title equally well, the one on the
  page nearest the bookmark's page takes it, then the earlier one. Before, the earlier heading won
  even a page away from the bookmark; spec section 8.4 asks for the nearest heading block (a
  deferred minor of Task 16, built in bccd67d).
- `clean_heading_artifacts` drops a one- or two-letter token of an OCR heading that echoes the end
  of the word before it or the start of the word after it, unless the language lists it as a real
  short word. The lists now hold "i" and "am" in English and "ia", "si" and "ya" in Indonesian, so
  "Why I Invest", "Here I am" and "Menjadi Si Sibuk" keep every word.
- If it turns out wrong: compare the ratio and then the order alone again; drop the added words.

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
  whose text came from OCR: a scanned page, a page without a text layer (text drawn as outlines,
  which Docling's auto OCR reads), or every page with `--ocr force`. The layout stage
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
- 2026-11-20: the re-review's fixes (the OCR score of a page without a text layer, the wording of
  the index warning) change report.json again; the version stays 8, since no release carried it.

## 2026-11-19: Optimizer: an image under 20 px on Xteink goes with a finding, its alt text stays

- On an Xteink device the optimizer removes an image whose short side is under 20 px, as before,
  but an `image_too_small` info finding now counts them, and an `<img>` of such an image is
  replaced by its alt text: "Press ![the power key](icon.png) to start." reads "Press the power
  key to start." Before, the image and its alt text went without a finding (spec section 5).

## 2026-11-19: Optimizer: a zip bomb is refused, and so is an entry name with a drive or backslash

- The optimizer refuses an EPUB with an entry that unpacks to more than 200 MB, or that unpacks to
  more than 2000 MB in all, as "Not a readable EPUB", before it reads any entry: the whole book
  is read into memory, and zipfile reads no more than the size each entry declares. No real book
  comes near either cap; a comic book of full-page scans reaches a few hundred MB in all. This
  matters once M2 accepts uploads.
- An entry name with a drive (`C:/x`, `C:x`) or a backslash is skipped with the `unsafe_path`
  warning, like a root or a ".." part. Python reads a backslash as "/" on Windows only, so on other
  systems such a name reached the output.

## 2026-11-19: CSS: a declaration starts only after "{", ";", "}" or the start of the text

- `rewrite_css` looks for a declaration only at the start of the text or after "{", ";" or the
  "}" of a nested block (after any white space and comments, which it keeps; a "*" before the
  name, an old IE hack, goes with the declaration), and steps over a string, group or comment
  outside a declaration whole. An unclosed comment runs to the end of the text, as CSS reads it. Tried at
  every position, crafted CSS took quadratic time: `a:a:a:...{` of 16 KB took 15.6 s, and an
  unclosed comment after every "{" took 0.8 s at 16 KB on Xteink; each now takes milliseconds,
  and the stylesheets of the tests come out the same.
- 2026-11-20, re-review: the first form left out "}" and the "*" hack, so a declaration after a
  nested block (`@page { @top-center {...} background: url(...) }`, CSS nesting) or behind
  `*` was no longer rewritten.

## 2026-11-20: Shared reading styles and font fallback (M5)

- The reading aid is named Focus Mode because "Bionic Reading" is a registered trademark. It uses a Typst text rule in XTC body text and keeps the original characters in the PDF text layer.
- Named styles live under the app data folder and the default name lives in `settings.json`. New GUI jobs and CLI conversions read the default; explicit CLI flags and panel changes override it.
- Current user input is validated strictly. Stored styles and jobs with a removed font load with Literata at the nearest available weight and emit a `font_missing` finding. Focus Mode turns off with a finding when no heavier weight remains.
- Shared font files live under `<data>/fonts/`; old job fonts remain readable. XTC conversion checks body text against the selected font cmap and reports missing characters. Live preview performs the same check for the displayed chapter.
- The GUI Fonts section is part of the existing Settings area on Select files. This keeps font management near conversion settings without another route.

## 2026-11-20: Native packages validate EPUBs with private Java

- The owner chose automatic EPUBCheck validation for every EPUB made by a native installation and separate native archives for Windows x64, macOS arm64, and Linux x64. A one-folder PyInstaller build carries Temurin JRE 21.0.13+9, EPUBCheck 5.4.0, its `lib/`, and license notices; no host Java or Python is needed. Third-party binaries are downloaded and SHA-256 checked at build time, never committed to Git.
- The optimized EPUB is written under its output directory, checked, and moved to the published name only after validation. Errors or a broken bundle fail the file; warnings remain findings. Source installs without either validation environment variable keep their existing behavior, while a partial configuration fails.
- The Windows build and smoke passed on this machine, including a 12-page PDF conversion with bundled validation. CI builds and smokes the other two archives on matching OS runners; fresh-machine installation checks remain separate.

## 2026-11-20: Focus Mode embedded in EPUB

- The existing reading style's Focus Mode also wraps word prefixes in presentational XHTML `<b>` elements during EPUB optimization. This covers Markdown, PDF, and EPUB inputs with one pass, and leaves code and math unchanged. EPUBCheck validates the resulting file before publication.
- The Select files settings expose the option before conversion; Review can change it and reconvert. EPUB readers may override book formatting, but no reader feature or script is required.
- The EPUB tab in Review exposes the Focus Mode switch and strength directly. Apply changes uses the existing rebuild route, preserving the original conversion.
- The EPUB preview uses the same Focus Mode setting as the exported EPUB, and the Review controls request a live chapter preview before Apply changes. It remains an approximate page layout because the actual e-reader controls pagination.

## 2026-11-20: End-to-end GUI redesign around a page map

- The owner asked for an end-to-end redesign that is elegant, minimal and effective and clear about conversion progress. Of three Convert-screen directions (quiet column, pipeline rail, page map) the owner chose the page map: the book drawn as one square per source page, used on Select (scanned pages), Convert (progress and findings) and Review (navigation strip). Spec: `docs/superpowers/specs/2026-11-20-end-to-end-redesign-design.md`; it supersedes the Guided Workspace spec for visuals and interaction.
- Review stays required before Export. Backend changes are additive only: page numbers in page events, a book event with scanned and blank pages, event timestamps, scanned/blank lists from inspect, and a recorded EPUBCheck outcome per EPUB.
- Inter is bundled with the app; the GUI loads no font from the network.
- Built on branch `redesign-page-map` (2026-11-21). Changes from the spec made while building: strings stay ASCII, so the " · " separators are joined in code; inputs keep a 3 : 1 edge (`#8A8A93`) beside the `#D4D4D8` control border; the model download shows a status line and its log, not a progress bar, because the server sends no fraction; Delete moved from Review to Convert's failure actions; the size line on Export says "from", not "down from"; the Review strip groups pages to about two pixels a bar on narrow screens.

## 2026-11-21: Page map redesign merged; version 0.2.0

- The owner merged `redesign-page-map` into `main` and chose version 0.2.0 for the new GUI. The uncommitted Guided Workspace polish that sat on `main` was stashed, not committed, because the redesign replaces those three files.
- No release tag was pushed: the owner deploys this version by running it locally for now.

## 2026-11-21: Page map polish (the deferred minors of the redesign review)

- The page map caption on Convert promises a click only when a click works: "Each square is one page." while the file converts, and the click hint once it is done.
- Review's top bar names the file that is ready to review as a link to it. The visible line is no live region any more; a hidden one speaks the words when they change, never each new percent.
- The Convert queue pills are rebuilt only when one changes, and a focused link gets the focus back. The elapsed time moves every second while a file runs, not only on events. The meta line names the kind of PDF (digital, scanned, partly scanned).
- Focus Mode says "changed" like the other controls; its strength is a select (Low, Medium, High), as the spec asks. "Text size" replaces "Font size" in the dock, notes read "Notes (N)", the findings column is 240 to 280 px, and the page map gap is a third of the square (4 px at 12 px, 2 px at 8 px).
- While files still convert, Apply's status keeps the count of pending changes beside "Available when every file has converted".
- The model download shows an indeterminate progress bar, hidden under reduced motion, because the server sends no fraction.
- Start waits for the reading style that was just chosen. An XTC carried through Apply stays an XTC when its color mode changed. Export gives an XTC's page count, from its preview, once it has loaded.
- README and README.id.md describe the four steps of the new GUI.
- After the branch review: the elapsed clock runs only while the job is queued or running and the server is reachable. A job that ends failed marks the file that was still running as failed, so a worker that died is no longer shown as running; Convert shows the job's error for it.
- Export reads an XTC's page count from the file's header (`GET /api/jobs/{id}/files/{n}/xtc-pages`), never from the preview, which would render the whole book first.
- Start stops with the error when the chosen reading style cannot load, and waits for a style chosen while it waits. The dock uses the spec's words (Line spacing, Side margins, First-line indent), and the findings column stays 240 to 280 px with Advanced typography open.

## 2026-11-21: Focus Mode weight, Focus Mode on Select, honest style UI, X4 Pro default

- eco's targets are EPUB and XTC with EPUB first, and the EPUB is read on Xteink only (owner). Spec: `docs/superpowers/specs/2026-11-21-focus-weight-honest-ui-design.md`.
- Focus Mode bolds a fixed share of each word in EPUB and XTC alike: 1 letter of words up to 3 letters, 2 of 4, and the nearest 40% of longer words. The strength setting is gone; one Python function and one Typst `#let` carry the rule, tested against one table.
- The user chooses the bold weight: Semibold 600 or Bold 700 (default 700). Medium 500 is not offered: on a reader font with only regular and bold, CSS shows 500 as regular and Focus Mode would vanish from the EPUB. In XTC, an uploaded font without the chosen weight uses the nearest heavier weight it has. Old styles with `focus_strength` still load; the CLI takes `--focus-weight`.
- Review says what reaches the EPUB: in the EPUB preview, text size, spacing and margins change only the XTC and the preview. A job that makes only an EPUB counts only Focus Mode and File size changes for Apply and Continue (File size changes its images); other changes are labelled as preview only, and Export names only what reached the EPUB.
- Select has a Focus Mode checkbox with a "?" button that opens a short explanation (a click, not a hover tooltip). It starts as the chosen reading style has it.
- The default device is the Xteink X4 Pro in the GUI and the CLI. A CLI run without `--device` now names its outputs `book.x4-pro.epub`.

## 2026-11-21: EPUB optimizations for Xteink

- The owner chose five of ten brainstormed EPUB optimizations; they run only for Xteink devices, for built EPUBs and EPUB inputs alike. Spec: `docs/superpowers/specs/2026-11-21-epub-xteink-optimizations-design.md`.
- Publisher sizes become relative: absolute `font-size` becomes `em` against 16 px (keywords too), absolute `line-height` becomes unitless (at least 1.2), `html` and `body` lose absolute margins and paddings, and other margins above 32 px are capped at 2em. Converting, not deleting, keeps headings bigger than body text.
- `color`, `background`, `background-color` and `background-image` go together, so white text never survives on a removed dark box. An image only a removed background used is dropped by a second unreferenced-file pass.
- Photos get `autocontrast(cutoff=1)` and a light unsharp mask; PNGs and line art are unchanged.
- Empty `p` and `div` (no text, image or id) and runs of `<br/>` go; a spine page with nothing to read is removed and every link, nav and NCX entry to it moves to the next page.
- A table of contents that is missing, empty or more than half broken is rebuilt from `h1` to `h3` (or one entry per page): an NCX always, a nav document too for EPUB 3 only, since EPUB 2 has no nav document. A working table of contents is never replaced.

## 2026-11-21: Xteink EPUB follow-ups

- The nav document and the NCX are judged each on its own; a missing or broken one is written from the one that works (the publisher's contents), and from the headings only when neither works. It is not known which file each Xteink firmware reads. Spec: `docs/superpowers/specs/2026-11-21-epub-xteink-followups-design.md`.
- The page box also covers `body` with a class or id, a class the book puts on its `<body>` (Calibre's `.calibre`), `@page`, and the style attribute of `<body>`. The `font` shorthand's size and line height become relative like `font-size` and `line-height`.
- An enhanced photo is never bigger than the same photo without enhancement: its quality steps down by 2, at most 15; then it keeps only the stretched levels, and failing that its plain encoding. The owner chose to keep the size; on the sample the JPEGs went from 16% bigger to 1% smaller at the default size.

## 2026-11-22: Honest options

- The page offers only choices that make different files. Layout: Reflowable text (`auto`) and Page images; `reflow` stays a CLI and API value equal to `auto` (the M1 gap is closed by not offering it). Firmware: Stock, and one choice for CrossPoint, CrossInk or not sure (`any`), which make the same files and the same preview; the server still takes `crosspoint` and `crossink`.
- X4, X4 Pro and X4 v2 Classic stay three choices (the file name follows the device) with a hint that they get the same files.
- The EPUB tile and the Review line say "Page images" for a PDF converted as page images. The XTC tile names the chosen device. An "Other e-reader" cannot open XTC: the page turns the tile off, and the API and the CLI refuse XTC with `general`.
- File size says it changes only the EPUB's images; the firmware hint says that Stock with Smallest leaves the EPUB's images out. OCR has a hint per choice and is off for Page images.
- `--landscape` (and `landscape` in the API) needs mode `pages`: it only turns page images.

## 2026-11-22: Focus Mode ExtraBold 800

- The owner asked for ExtraBold 800 beside Semibold 600 and Bold 700. The bundled Literata, Bitter and Lexend Deca gained their 800 face (same sources and commits, `src/eco/fonts/SOURCES.md`); Libertinus Serif has none.
- A Focus Mode weight must be a weight of the font and heavier than the text. A new style with another one is refused; an older one moves to the next weight the font has, with a `focus_weight_missing` finding, instead of Typst drawing another weight under the chosen name. The dock offers only the weights the font has.
- In the EPUB on an Xteink the reader's font decides; with only regular and bold faces 600, 700 and 800 all show bold. The dock note says so. Not checked on a device.

## 2026-11-22: Chapter splits open big wrappers and cut at headings

- An InDesign export holds a whole chapter in one container beside an empty one, so the split stopped at the outer wrapper and left a 228 KB part with the warning "one element is larger than the limit" (seen with Focus Mode on). A wrapper (div, section, article) larger than the limit is now opened: its children go into copies of it, the class on each and the id on the first. A wrapper with loose text between its children stays whole, so no text moves.
- A full part moves its cut back to its last heading (h1-h6, or a wrapper that starts with one) when at least half the limit stays behind, so a part starts at a section rather than mid-section. The builder's own Markdown chapters use the same rule (`pack` in `eco/epub/split.py`).
- Each part still starts on a new screen on the reader; that is the cost of the 100 KB limit.
