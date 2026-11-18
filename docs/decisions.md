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
