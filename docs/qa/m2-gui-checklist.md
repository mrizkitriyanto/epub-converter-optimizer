# M2 web GUI: manual QA checklist

Acceptance criterion 12 of the design spec (section 9): the GUI works in Chrome, Firefox and Safari.
Upload to download works. Progress shows stages and pages. Cancel stops within 10 s. A click on a
finding moves both panes. Change settings does not repeat OCR. Network mode refuses requests without
the token.

This list is run by a person, in each browser. The first group covers that criterion. The next groups
cover what a browser run has to check first, the gate without models, the file rows, and the fixes
made after the final review (delete, "View as", Ctrl+C). The results table is at the bottom.

## Before you start

- Browsers: the current Chrome, Firefox and Safari (Safari on macOS). Run every step in all three
  browsers. The `curl` commands of A10 need no browser; the browser parts of A10, B9 and B10 differ between
  browsers too, so run them in all three.
- Start the server with `eco web --no-browser --data DIR` (stop it with Ctrl+C). It prints
  `Open: http://127.0.0.1:8000/`. Open that address yourself.
- Two data folders: one empty (no models) and one where `eco setup` has run. A step says which one it
  needs. Starting the model download from the page downloads about 417 MB: do it once.
- Window widths: 1280, 1000 and 390 px. Use the browser's responsive mode.
- Files, from your own books (never commit them): a Markdown file; a large Markdown file (several
  hundred KB); an EPUB; a digital PDF of about 100 pages; a scanned PDF; a PDF with pictures; a text
  file renamed `damaged.pdf`; a `report.docx`.
- Each step lists what to do and what you should see. The words in quotes are the page's own text.
- Fill in the results table at the bottom: `pass`, `fail` or `not run`, and a note for a fail.

## A. Acceptance criterion 12

- **A1 Setup gate** (empty data folder). The page opens on "AI models needed". It lists the three
  models with their sizes (172, 213 and 32 MB) and "Total: 417 MB". The primary button reads
  "Download models (~417 MB)". Click it: the button reads "Downloading…", a log shows progress, and
  when the models are ready the page moves to "Files". With models in place, a reload opens "Files"
  directly.
- **A2 Upload together.** Add the Markdown file, the EPUB and the PDF in one go. "Start conversion (3
  files)" is enabled. Click it. Processing shows "(file 1 of 3)" in the heading and runs the three
  files. Review & download opens for the first one; the "File" list holds all three.
- **A3 Progress.** With the PDF running: the bar moves, the line reads "Page i of n", and the stage
  list shows "Reading PDF", "Recognizing page layout", "Fixing code, formulas and reading order",
  "Building EPUB" and "Optimizing and compressing", each marked done, in progress or waiting. A PDF in "Page images" has no "Fixing code, formulas and reading order" stage. A
  Markdown file shows only the last two stages.
- **A4 Cancel.** Start a PDF of about 100 pages and click "Cancel" while it runs. The button reads
  "Cancelling…", the job ends within 10 s, and Review shows "The conversion was cancelled." Start two
  jobs and cancel the second while it waits: it ends at once.
- **A5 Reload restores the job.** Reload during Processing: the same stage shows again and the live
  updates continue. Reload in Review: the same job opens in Review, on its first converted file and page 1 (the
  address holds only `#job=ID`, so the file and the page you were on are not kept).
- **A6 A finding moves both panes.** Open a PDF whose findings list is not empty. Click a finding with
  a page: the original page (caption "Original PDF, page N") and the device page (caption "Page N of
  M") both move to it.
- **A7 View as Stock hides images.** On a PDF with pictures or an EPUB with images, set "View as" to
  "Stock": the images disappear from the device page. "CrossPoint" and "CrossInk" show them. The page
  you are on stays.
- **A8 Change settings does not repeat OCR.** Convert a scanned PDF (Layout "Automatic" or
  "Reflowable text", models ready). In Review click "Change settings", pick another "File size" and
  click "Apply changes". Processing opens a new job: "Reading PDF", "Recognizing page layout" and
  "Fixing code, formulas and reading order" show "already done", and the job ends in seconds.
- **A9 Downloads open in an e-reader app.** Click "Download EPUB" for a Markdown file, an EPUB and a
  PDF. The file is named like `book.x4.epub`. Open each in an e-reader app (Apple Books, Calibre, or
  the e-reader itself). The text, the chapters and the cover show.
- **A10 Network mode refuses requests without the token.** Run `eco web --host 0.0.0.0 --no-browser`
  (the system may ask about a firewall: allow it for this test). It prints
  `Open: http://127.0.0.1:8000/?token=...` and "On another device, use this computer's network
  address in place of 127.0.0.1." From another device, or from this computer with its network
  address, run `curl -i http://ADDRESS:8000/` and `curl -i http://ADDRESS:8000/api/jobs`: both answer
  401 `{"error":"Missing or invalid token"}`. A browser on another device at the printed address,
  with the computer's network address in place of `127.0.0.1`, shows the page, and the token is gone
  from the address bar. A wrong token gives 401. Without `--token` the token is made up and printed;
  with `--token` it is the one you gave.
- **A11 Keyboard only.** Do the whole path from Select files to the download with the keyboard: Tab
  and Shift+Tab reach every control in a sensible order, the focus ring is visible at each stop, Enter
  and Space press buttons, the arrow keys change the selects and the page.

## B. What a browser run must check first

In this order: these are the places where the script is least tested.

- **B1 The drop zone.** It is a `<label>` around a hidden file input. Click, Tab, Enter and Space open
  the picker. The focus ring shows on the zone. A dragged file highlights the zone and drops. A
  dropped `report.docx` gives "Unsupported file type: report.docx" and no row. "Remove" leaves the
  focus on a sensible control.
- **B2 The stream.** Start, Processing, Review for a Markdown file (a second or two). In the network
  tab the event stream closes at its end, with no reconnect loop. The browser's Back button returns to Select files. A
  reload on an address with `#job=` restores each state: queued, running, done, failed, cancelled. The
  heading takes the focus at each change of stage.
- **B3 A PDF with models.** The bar and "Page i of n" move. The time left ("about N min left")
  appears only after two live page events, and is not absurd after a reload. A rebuilt PDF shows its
  first stages as "already done". The feed of findings stays at the bottom.
- **B4 The live preview under the real CSP.** In Review click "Change settings". The picture shows
  without a console error (the page loads it as a `data:` image). "Updating preview…" stays until the
  answer arrives. Move the slider or the select quickly: only the last answer shows. "Apply changes"
  goes to the new job. Escape and "Close" put the stored page back. The caption reads "Preview with
  the new settings: page N of M of this chapter".
- **B5 Sync in Review.** A finding goes to the right device page and original page. The left and right
  arrow keys and the "Previous page" and "Next page" buttons turn the page. "View as" keeps the
  place. Check a PDF in "Page images" (a device page can hold two source pages and the map gives one),
  a PDF in "Reflowable text", and a large Markdown file (the text pane, "Text of the book
  (Markdown)"). Check the device frame for an Xteink X3 (528 x 792) and an Xteink X4 (480 x 800).
- **B6 The layout.** At 1280, 1000 and 390 px, with and without the Change settings panel: no
  horizontal scroll, the stepper wraps, tap targets are 44 px, the findings list scrolls.
- **B7 Cancel.** A running job ends within 10 s and Review says it was cancelled. A queued one ends at
  once.
- **B8 The setup gate on an empty data folder.** The list, the total and the button text are as in
  A1. A failed download needs a network that fails (yours): turn the network off during the download.
  The gate shows "The download did not finish." and both retry buttons: "Try again" and "Try again
  over IPv4". Both start a new download.
- **B9 Network mode on this computer.** Run `eco web --token TOKEN --no-browser` (16 or more of A-Z,
  a-z, 0-9, - and _). Open `http://127.0.0.1:8000/?token=TOKEN`. It redirects to `/` and the address
  bar has no token. The upload, the event stream, the pictures and the download all work with the
  cookie.
- **B10 An upload above the limit.** Run `eco web --max-upload-mb 1`. Add a file over 1 MB and start.
  The server answers 413 "File too large (limit 1 MB)", but a browser that is still sending may show
  a network error instead of reading the answer. Write down what you see. The Select files page must
  stay usable.
- **B11 The server stops in a conversion.** Stop `eco web` (Ctrl+C) in the middle of a PDF conversion.
  The page shows "The eco server stopped. Start it again, then reload this page." Start it again and
  reload: the job shows as stopped, with its error.
- **B12 Keyboard and screen reader.** A keyboard-only pass of every stage. With a screen reader (VoiceOver
  on macOS): the live regions (progress, findings, the feed) are not too talkative. A findings list
  with hundreds of items is announced whole when the file changes: write down whether that is bearable.

## C. Without the AI models

Use the empty data folder.

- **C1 Continue without models.** On the gate click "Continue without models". "Files" opens. Under
  the drop zone the note reads "Without the AI models, PDFs convert only with Layout set to Page
  images." with a "Download models" button.
- **C2 What converts.** A Markdown file and an EPUB convert. A PDF with "Advanced settings" > "Layout"
  set to "Page images" converts. A PDF with "Layout" at "Automatic" or "Reflowable text" ends
  "Failed" with the message "AI models are not installed. Run: eco setup".
- **C3 Try again.** Review of that failed job shows the message, and the "Try again" button is
  enabled. Click it with the settings unchanged: the new job fails the same way, and its Review has
  "Try again" enabled too.
- **C4 A failed file.** "Change settings" and "Download EPUB" are not offered for a file that was not
  converted. In a job with several files, the "File" list marks it "(not converted)".

## D. The fixes of Task 9

- **D1 The panel starts closed.** In Review open "Change settings", then click "Apply changes". The
  new job's Review starts with the panel closed. Open it again: the button reads "Apply changes", not
  "Applying…".
- **D2 Leaving Review with the panel open.** Open the panel, then leave Review through the stepper
  ("Select files") or a link in "Recent conversions". The next Review starts with the panel closed.
- **D3 Two jobs from Recent conversions.** Convert two files in one job, and two other files in a
  second. From "Recent conversions" open the first, then the second: the "File" list shows the second
  job's names.
- **D4 A reload in a PDF conversion.** Reload in the middle of a PDF conversion: the time left is not
  absurd (no thousands of minutes).
- **D5 A failing preview picture.** Make a preview picture fail (stop the server, or block the
  request in the browser tools), then change page quickly. The failure text does not stay under the
  new page.
- **D6 The XTC hint.** The hint "Coming in a later version" under the XTC toggle in the preview sits
  on its own line at 1280, 1000 and 390 px, with no horizontal scroll.
- **D7 The gate during a download.** Empty data folder: click "Download models (~417 MB)", then at
  once "Continue without models". On Select files click "Download models". The gate shows the
  download still running ("Downloading…") and its primary button is disabled. When the download
  ends, the models note on Select files goes away by itself.

## E. The file rows

Each PDF is read by the server before it is converted (one file at a time).

- **E1 The row text.** A PDF row shows "Reading…", then reads like `9.4 MB · 802 pages · Digital PDF
  · about 9 min`: size first, then pages, then Digital PDF, "Scanned, uses OCR", "Scanned, no OCR" or
  "Partly scanned (N of M pages)", then the estimate. A Markdown or EPUB row shows its size and its
  type ("Markdown" or "EPUB").
- **E2 The estimate follows the settings.** Change "Layout" and "Text recognition (OCR)" in
  "Advanced settings": the estimate moves. "Page images" makes it much smaller; "Off" and "Every page"
  change it for a scanned PDF.
- **E3 Models missing.** With the empty data folder and "Layout" at "Automatic", the warning "Needs
  the AI models. Download them, or set Layout to Page images." replaces the estimate. "Page images"
  brings the estimate back.
- **E4 Focus.** Add several PDFs. While other rows still say "Reading…", Tab to a "Remove" button: the
  focus stays on it when the answers arrive.
- **E5 Remove and Start while reading.** Remove a PDF while it is being read: the reading stops and the
  next PDF starts. Click "Start conversion" while a PDF is being read: the reading stops and the upload
  begins. If the upload fails (stop the server), reading resumes.
- **E6 Bad PDFs.** A PDF over the upload limit (`--max-upload-mb 1`) and `damaged.pdf`: see what the
  row shows. Neither may leave the page stuck; the other rows still read.
- **E7 The models note.** Empty data folder: "Download models (~417 MB)" on the gate, then "Continue
  without models": the note says the models are downloading. A failed download (a network that
  fails) shows the failure note on Select files: "The model download did not finish. Without the AI
  models, PDFs convert only with Layout set to Page images." When the models become ready while the
  "Download models" button has the focus, the focus moves to the "Files" heading.
- **E8 Widths.** The rows at 390, 1000 and 1280 px: the text wraps, there is no horizontal scroll,
  "Remove" stays reachable.

## F. The M2 fix wave

- **F1 Delete a conversion.** In Review of a finished job click "Delete conversion". The browser
  asks "Delete this conversion? The uploaded files, the EPUB files and the previews are removed, and
  this cannot be undone." Cancel keeps everything as it was. OK: the button reads "Deleting…", then
  the page shows Select files, and "Recent conversions" no longer lists the job. The browser's Back
  button does not open it again. Delete a job that a second tab has open, then click "Delete
  conversion" in that tab: it goes to Select files too. With the server stopped, "Delete conversion"
  shows the reason under the buttons and reads "Delete conversion" again. The buttons still wrap at
  390 px, and "Download EPUB" stays the one primary button.
- **F2 View as during a live preview.** In Review open "Change settings", move the font size, and at
  once change "View as". No text like "Cannot read properties of null" shows under the device page;
  the preview of the new view loads.
- **F3 Ctrl+C during a conversion.** Start a conversion that takes a while (a PDF of about 100
  pages), then press Ctrl+C once in the terminal of `eco web`. The server stops within a few seconds
  with no traceback. Start it again: the job shows "The server stopped before this file was
  converted.", not "The conversion stopped unexpectedly (exit code 1)."

## Results

Fill in the browser columns. The `curl` column is the server half of a step, run on 2026-11-18 on
Windows against a real `eco web` on 127.0.0.1 with files from `tests/fixtures/make.py` (no browser was
used on that machine). `not run here` means the step needs a browser, the AI models or a network that
fails.

| Step | curl, 2026-11-18 | Chrome | Firefox | Safari |
|---|---|---|---|---|
| A1 | not run here: the model download is 417 MB and needs a yes; `GET /api/setup` pass (3 models, total_mb 417, ready false); browser half not run here: browser QA awaits the owner | | | |
| A2 | pass: Markdown, EPUB and a Page-images PDF in one `POST /api/jobs` (201), one job, all three done; browser half not run here: browser QA awaits the owner | | | |
| A3 | pass: the stream carries stage events and `{"type": "page", "done": 1, "total": 1}` and ends at `end`; browser half not run here: browser QA awaits the owner | | | |
| A4 | pass: a waiting job cancelled at once (202, status `cancelled`); a running job not run here: the fixtures convert too fast; browser half not run here: browser QA awaits the owner | | | |
| A5 | pass: `GET /api/jobs/ID` returns the finished job and its files; browser half not run here: browser QA awaits the owner | | | |
| A6 | pass: `/pages` returns page_map and chapters, and `/source/1.png` and `/preview/epub/1.png` answer 200 image/png; browser half not run here: browser QA awaits the owner | | | |
| A7 | pass: the preview PNG of a file with images differs between `view=crosspoint` and `view=stock`; browser half not run here: browser QA awaits the owner | | | |
| A8 | not run here: needs the Visual C++ runtime (Q-14); a Page-images PDF rebuild (`POST /rebuild`, 201) converts again and shows no "already done" stage, as designed | | | |
| A9 | pass: downloads answer 200 `application/epub+zip`, `Content-Disposition` `notes.x4.epub`, start with `PK`; opening in an e-reader app not run here: browser QA awaits the owner | | | |
| A10 | not run here: the `--host 0.0.0.0` run is the owner's; on 127.0.0.1 with `--token`: no token 401, `?token=` 302 and cookie, cookie 200 (see B9); the two printed lines are checked by the CLI tests | | | |
| A11 | not run here: browser QA awaits the owner | | | |
| B1 | not run here: browser QA awaits the owner; server half: a `.docx` upload gives 400 "Unsupported file type: report.docx" | | | |
| B2 | pass: the stream closes at `end`; `GET /api/jobs/ID` after it shows done; the states queued, failed and cancelled each seen in the JSON; browser half not run here: browser QA awaits the owner | | | |
| B3 | not run here: needs the Visual C++ runtime (Q-14); browser QA awaits the owner | | | |
| B4 | pass: `/live.png?chapter=0&font_size=40&size=small` answers 200 with `X-Excerpt-Index` and `X-Excerpt-Pages`; `page` with `chapter` gives 422 "Give exactly one of page and chapter"; the CSP header is `img-src 'self' data:`; browser half not run here: browser QA awaits the owner | | | |
| B5 | pass: page map, chapters, source and device pages, `/text` (200), source of a Markdown file 404 "This file has no source pages", page 99 404 "No such page"; browser half not run here: browser QA awaits the owner | | | |
| B6 | not run here: browser QA awaits the owner | | | |
| B7 | pass: the same server half as A4; browser half not run here: browser QA awaits the owner | | | |
| B8 | pass: `GET /api/setup` on a fresh folder; `GET /api/setup/events` before a download gives 404 "No download has started"; the download itself and a failed download not run here: browser QA awaits the owner | | | |
| B9 | pass: no token 401, wrong token 401, `/?token=TOKEN` 302 to `/` with `eco_token` (`HttpOnly; SameSite=strict`), cookie and Bearer header 200, upload, stream, picture and download 200 with the cookie and 401 without, a POST with a foreign `Origin` 403; browser half not run here: browser QA awaits the owner | | | |
| B10 | pass: with `--max-upload-mb 1` a 2 MiB upload gives 413 "File too large (limit 1 MB)" (also on `/api/inspect`) and leaves no job folder; 201 files give 400 "Too many files (limit 200)"; what a browser shows not run here: browser QA awaits the owner | | | |
| B11 | not run here: the fixtures convert too fast to stop in the middle; browser QA awaits the owner | | | |
| B12 | not run here: browser QA awaits the owner | | | |
| C1 | not run here: browser QA awaits the owner | | | |
| C2 | pass: Markdown, EPUB and a Page-images PDF done; a PDF in "auto" and in "reflow" ends failed with "AI models are not installed. Run: eco setup"; browser half not run here: browser QA awaits the owner | | | |
| C3 | pass: `POST /rebuild` of the failed job with the same options fails again with the same message; with `{"mode":"pages"}` it is done; browser half not run here: browser QA awaits the owner | | | |
| C4 | pass: a failed file has no output (download 404 "No such output file", preview 409 "This file has not been converted yet"); browser half not run here: browser QA awaits the owner | | | |
| D1 | not run here: browser QA awaits the owner | | | |
| D2 | not run here: browser QA awaits the owner | | | |
| D3 | not run here: browser QA awaits the owner | | | |
| D4 | not run here: browser QA awaits the owner | | | |
| D5 | not run here: browser QA awaits the owner | | | |
| D6 | not run here: browser QA awaits the owner | | | |
| D7 | not run here: browser QA awaits the owner | | | |
| E1 | pass: `POST /api/inspect` of a PDF returns `{"pages", "scanned_pages", "seconds_per_page": {"digital", "scanned", "pages"}}`; browser half not run here: browser QA awaits the owner | | | |
| E2 | not run here: browser QA awaits the owner | | | |
| E3 | not run here: browser QA awaits the owner | | | |
| E4 | not run here: browser QA awaits the owner | | | |
| E5 | not run here: browser QA awaits the owner | | | |
| E6 | pass: `damaged.pdf` gives 400 "Not a readable PDF: damaged.pdf" and a Markdown file 400 "Only PDF files can be inspected"; a PDF over the limit gives 413 (see B10); browser half not run here: browser QA awaits the owner | | | |
| E7 | not run here: browser QA awaits the owner | | | |
| E8 | not run here: browser QA awaits the owner | | | |
| F1 | pass: `DELETE /api/jobs/ID` while the job runs gives 409 "This conversion has not finished. Cancel it before you delete it."; once it is done, after its pages and a live page were rendered, 204 with no body, and its folder (uploads, outputs, previews) is gone; then `GET /api/jobs/ID`, its `/pages` and a second DELETE give 404 "No such job" and `GET /api/jobs` no longer lists it; an EPUB job whose book was read for the preview leaves no other folder; a DELETE with a foreign `Origin` gives 403; `DELETE /api/jobs` gives 405; browser half not run here: browser QA awaits the owner | | | |
| F2 | not run here: browser QA awaits the owner | | | |
| F3 | not run here: needs a long conversion and a Ctrl+C in the server's own terminal; the owner runs it | | | |
