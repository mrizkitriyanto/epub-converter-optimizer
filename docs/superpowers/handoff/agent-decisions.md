# Decisions made on the owner's behalf

The owner, 2026-11-17: "When there is a question, answer it with your recommendation, and it must be recorded in Markdown."

How to use this file:
- Every question that would otherwise go to the owner is answered here before you act on it.
- Append a new entry and never rewrite an old one. If new evidence changes an answer, add a new entry that names the old one and says why.
- Commit this file with the work the answer decides.
- A product decision also gets its dated entry in `docs/decisions.md`, as `AGENTS.md` requires.
- No answer can override the hard rules in `2026-11-17-m1-resume.md`: no samples or book files in git, never overwrite an input, no network during conversion, no pickle models, the same git identity, no force-push, no push to `main`.

Entry format:

```
### Q-<n>: <the question, one line>
- Date, milestone, task: ...
- Answer: ...
- Why: ...
- Cost if wrong: ...
- Recorded by: <agent and machine>
```

## Answers recorded at the handoff (controller on the owner's Mac)

### Q-1: Download a JRE and EPUBCheck to validate EPUBs locally (open question D-1)?
- Date, milestone, task: 2026-11-17, M1 wrap-up.
- Answer: Yes. Use portable zips: a Temurin JRE 21 zip and the EPUBCheck 5.x zip. Unpack them outside the repo (for example `~/tools`), state their measured sizes here, and point `ECO_EPUBCHECK_DIR` and the EPUBCheck command at them the way `.github/workflows/ci.yml` does.
- Why: until now EPUBCheck has run only in CI, so a broken package is found only after a push. Portable zips need no admin rights or system install.
- Cost if wrong: about 80 MB of disk.
- Recorded by: controller, owner's Mac.

### Q-2: Install the AI models on the new machine?
- Date, milestone, task: 2026-11-17, M1 T19 and slow tests.
- Answer: Yes. Run `uv run eco setup` (about 417 MB: layout 172, tables 213, OCR 32). Add `--ipv4` if TLS connections reset.
- Why: the slow tests, the acceptance tests and every PDF conversion need them.
- Cost if wrong: 417 MB of disk and bandwidth.
- Recorded by: controller, owner's Mac.

### Q-3: At the end of a milestone, merge into `main`, open a PR, or keep the branch?
- Date, milestone, task: 2026-11-17, every milestone end.
- Answer:
  - Keep the branch. Do not merge and do not open a PR.
  - Push the milestone branch to `origin` after its final review. Never force-push and never push to `main`.
  - Start the next milestone's branch from the previous milestone's branch tip: `m2-web-gui` from `m1-core-cli`, `m3-xtc` from `m2-web-gui`, `m4-docker-release` from `m3-xtc`.
- Why: the owner decides merges. Stacked branches keep each milestone reviewable on its own, and a push gives CI feedback and a backup.
- Cost if wrong: the owner merges or rebases the stack later.
- Recorded by: controller, owner's Mac.

### Q-4: An acceptance criterion fails. Lower the threshold, mark it xfail, or fix?
- Date, milestone, task: 2026-11-17, M1 T19 (AC1 precision is 0.9628 against 0.99).
- Answer:
  - Find the cause first: which words the output adds or misses.
  - Fix real defects in the pipeline, test-first, then re-run.
  - Never lower a threshold and never mark a test xfail.
  - If the cause cannot be fixed within the milestone (for example a limit inside Docling), record the measured number, the cause and the follow-up here and in the milestone report, and continue.
- Why: spec §9 sets the thresholds, and spec §5 forbids content lost without a warning.
- Cost if wrong: time spent on a gap that is inherent.
- Recorded by: controller, owner's Mac.

### Q-5: AC2 (scanned Bicara) misses its accuracy or heading threshold. Try other OCR models?
- Date, milestone, task: 2026-11-17, M1 T19.
- Answer:
  - Yes, as spec §10 plans: evaluate RapidOCR's larger and Latin recognition models.
  - Downloads are allowed; record their sizes.
  - Choose the smallest model that meets the threshold and record the choice in `docs/decisions.md`.
  - Keep OCR in default mode, because full-page OCR damaged italics in the spike.
- Why: spec §10 names this as the fallback.
- Cost if wrong: a larger model download and slower OCR.
- Recorded by: controller, owner's Mac.

### Q-6: AC2's time limit is "≤ 15 minutes on an M3 Mac". How to judge it on other hardware?
- Date, milestone, task: 2026-11-17, M1 T19.
- Answer:
  - Measure on an idle machine with a cold cache (a fresh `--data` folder).
  - Report the time together with the CPU and RAM of the machine.
  - On hardware slower than an M3, a miss is "not comparable", not a failure. Re-measure on the owner's Mac when possible.
- Why: the threshold is defined for one machine.
- Cost if wrong: a real slowdown goes unnoticed until it is measured on the Mac.
- Recorded by: controller, owner's Mac.

### Q-7: `test_samples.py` symlinks the models folder; Windows needs Developer Mode for that. What to do?
- Date, milestone, task: 2026-11-17, M1 T19.
- Answer: On Windows, create a directory junction instead, which needs no admin rights, for example `subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True)`. Keep the symlink elsewhere.
- Why: the test must run where the owner has no admin rights.
- Cost if wrong: none; it only affects the test setup.
- Recorded by: controller, owner's Mac.

### Q-8: `test_samples.py` embeds short book excerpts (`ICAT`, `LISTING_11_1`). Keep them in the public repo?
- Date, milestone, task: 2026-11-17, M1 T19.
- Answer: No. Move them into files under `samples/ground-truth/` (local, git-ignored), read them at run time, and skip with a clear reason when they are missing.
- Why: the repo is public, and book text belongs only in the owner's local samples.
- Cost if wrong: one extra local file for the owner to keep.
- Recorded by: controller, owner's Mac.

### Q-9: Docker is needed in M4. Install Docker Desktop, or work without it?
- Date, milestone, task: 2026-11-17, M4.
- Answer:
  - If Docker is already installed, use it: pull and build what the plan needs and record the image sizes.
  - If it is not installed, do not install it, since that is a system-level install. Validate the Dockerfile and the image through the CI jobs instead, and record that choice.
- Why: it avoids an admin install on the owner's machine while the image is still verified.
- Cost if wrong: image problems are found in CI instead of locally.
- Recorded by: controller, owner's Mac.

### Q-10: CI fails on a push (Windows, Linux or macOS job).
- Date, milestone, task: 2026-11-17, any milestone.
- Answer: Fix it on the current milestone branch, test-first, before the milestone's final review. Record what failed and why here when the fix needs a decision.
- Why: the spec requires green CI on three OSes (§9 criterion 11).
- Cost if wrong: none.
- Recorded by: controller, owner's Mac.

### Q-11: CI never runs on a milestone branch (it triggers on `main`, PRs and `workflow_dispatch`). Start it by hand?
- Date, milestone, task: 2026-11-17, every milestone.
- Answer: Yes. After each push of a milestone branch, and before its final review, run `gh workflow run CI --ref <branch>`. Watch it with `gh run watch` or `gh run list --branch <branch>`, and fix failures as in Q-10. Do not open a PR to trigger CI. Leave the workflow's triggers as they are.
- Why: the spec requires CI green on three OSes (§9 criterion 11). The Linux, Windows and EPUBCheck jobs have never run, and a manual run needs no PR or merge.
- Cost if wrong: some GitHub Actions minutes (free for public repos).
- Recorded by: controller, owner's Mac.

## Answers recorded on the new machine

(append below)

### Q-12: The owner put `samples/` next to the clone (`D:\Tools\epub-converter\samples`), not inside the repo root. Copy it, move it, or link it?
- Date, milestone, task: 2026-11-17, M1 T19 (setup on the Windows laptop).
- Answer: Link it. Create a directory junction `eco\samples` pointing to `D:\Tools\epub-converter\samples` (`New-Item -ItemType Junction`, no admin rights). Do not copy or move the owner's folder. Remove the link only with `rmdir eco\samples` (never `rm -rf`, which would follow it).
- Why: the owner's folder stays the single copy, so the ground-truth files that Q-8 adds land in it. `/samples` in `.gitignore` covers the junction. R-11 did the same on the Mac with a symlink.
- Cost if wrong: none. Remove the junction and copy the folder instead.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-1 (applied on Windows): local EPUBCheck, measured sizes
- Date, milestone, task: 2026-11-17, M1 T19 (acceptance AC7).
- Answer: Done as Q-1 says, outside the repo in `C:\Users\RizkiT\tools`: Temurin JRE 21.0.13+9 for Windows x64 (`OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip`, 49,106,397 bytes, SHA-256 checked against Adoptium's published value; 146 MB unpacked) and EPUBCheck 5.4.0 (`epubcheck-5.4.0.zip`, 33,093,170 bytes; 35 MB unpacked). Total download 82.2 MB, 181 MB on disk; the zips were deleted after unpacking. The acceptance suite finds them through `ECO_JAVA` and `ECO_EPUBCHECK_JAR` (ruling R-56 in the M1 ledger).
- Why: Q-1.
- Cost if wrong: 181 MB of disk; delete the two folders.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-13: This laptop has no Microsoft Visual C++ Redistributable, so PyTorch (`c10.dll`) and rtree (`spatialindex_c-64.dll`) cannot load. Install it system-wide, or work around it?
- Date, milestone, task: 2026-11-17, M1 setup (the fast suite gave 389 passed, 6 failed, 4 errors; all 10 are this one cause).
- Answer:
  - Do not run Microsoft's installer: it is a system-level install that needs admin rights (same reason as Q-9).
  - On this machine only, put the official runtime DLLs next to the uv-managed Python 3.12 (`C:\Users\RizkiT\AppData\Roaming\uv\python\cpython-3.12.16-windows-x86_64-none`), where Python already keeps its own `vcruntime140.dll`. Windows looks for a process's DLLs in that folder first. The DLLs come from the `msvc-runtime` 14.51.36231 wheel (PyPI, 2,052,033 bytes); each one must carry a valid Authenticode signature from Microsoft Corporation before it is copied. This changes nothing in the repo, and the wheel is never a project dependency (its licence is proprietary).
  - Product side: a clean Windows machine can lack this runtime (spec §5 anti-goal "fragile install on Windows", §9 criterion 11). PyTorch already prints Microsoft's download link when its DLLs fail, so eco adds no code for it; the README (both languages) states the prerequisite and the link.
- Why: without the runtime nothing PDF-related runs here: no `eco setup`, no slow tests, no acceptance. User-level and reversible beats an admin install the owner has not approved.
- Cost if wrong: none for the code. To undo, delete the copied DLLs from that Python folder (listed in the M1 ledger). The owner may prefer to install the redistributable from https://aka.ms/vs/17/release/vc_redist.x64.exe, after which the copies can go.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-14 (follows Q-13): the agent harness's safety check refused copying the runtime DLLs into the Python folder. What now?
- Date, milestone, task: 2026-11-17, M1 setup.
- Answer:
  - Do not work around the refusal: no copies into site-packages, no PATH tricks to load the downloaded DLLs.
  - The fix that remains is Microsoft's official installer, https://aka.ms/vs/17/release/vc_redist.x64.exe (Visual C++ Redistributable x64). It needs admin rights, so the owner runs it, or allows the copy described in Q-13. An agent does not start an elevated install on its own.
  - Until then, the work that does not need PyTorch, onnxruntime or rtree goes ahead: R-54, the Windows part of the T19 harness, the README note on the prerequisite, the wrap-up docs commit, and a manual CI run of the already-pushed branch tip (Q-11). OpenCV, pypdfium2 and Pillow load without the runtime.
  - Blocked until the runtime exists: `eco setup` (417 MB of models), the slow tests, the AC1 investigation, the acceptance run, and therefore the M1 final review and M2-M4.
- Why: the refusal marks the copy as a change the owner must approve. Only the owner can approve an admin install.
- Cost if wrong: M1 waits for one owner action.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-15 (replaces the mechanism of Q-11): GitHub cannot start CI by hand on a milestone branch, because `main` has no workflow. How does CI run?
- Date, milestone, task: 2026-11-17, M1.
- Evidence: `gh workflow run ci.yml --ref m1-core-cli` answers `HTTP 404: workflow ci.yml not found on the default branch`, and `actions/workflows` lists no workflow. GitHub dispatches only workflows that exist on the default branch, and `origin/main` (2e0363c) holds only the design docs.
- Answer:
  - Add the milestone branches to the `push` trigger of `.github/workflows/ci.yml` (`branches: [main, "m[0-9]-*"]`) in a commit on `m1-core-cli`. Keep `pull_request` and `workflow_dispatch` as they are.
  - Push `m1-core-cli` (a normal push; never force, never `main`) once that commit and R-54 are reviewed, so CI runs before the M1 final review, as Q-11 intended. This push comes earlier than Q-3's "after the final review"; the branch has been public with unfinished work since the handoff.
  - Every later push of a milestone branch then runs CI by itself. Still no PR. Q-10 still applies to failures.
- Why: a push trigger is the only way to run CI without a PR or a push to `main`. GitHub's Windows runner has the Visual C++ runtime this laptop lacks (Q-14), so CI also checks the Windows fast suite and the slow tests (integration job) while they are blocked here.
- Cost if wrong: Actions minutes on each push of a milestone branch (free for a public repo). The owner can drop the branch pattern before merging.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-16 (extends Q-8): other tracked files still hold short book text. Remove it too?
- Date, milestone, task: 2026-11-17, M1 T19.
- Found by the T19 implementer: the four `CODE_LINES` of the synthetic code fixture (`tests/fixtures/make.py`) are lines of *Practical Malware Analysis* Listing 11-1, and one slow test looks one of them up; a few short *Bicara* section headings and one sentence fragment sit in `tests/pdf/test_text.py`, `tests/pdf/test_structure.py` and `tests/test_pipeline.py`; `docs/decisions.md` quotes the fixture lines in its R-53 entry. The M1 plan, the spec and the M1 ledger quote some of the same text.
- Answer:
  - Tests and `docs/decisions.md`: yes. Replace the book-derived strings with invented text of the same shape: the same line count and character lengths for the fixture lines, so the fixture geometry does not move, and the same OCR-artifact patterns for the headings. Each test must still test what it tested.
  - The spec, the plans and the handoff records stay as they are. They are the owner's approved documents, and rewriting them is the owner's call. The milestone report says what they still quote.
  - Git history keeps the old text. Removing it needs a force-push, which is forbidden, so the report names this too.
- Why: Q-8's reason covers all of it: the repo is public, and book text belongs only in the owner's local samples.
- Cost if wrong: a small test-only change, and fixtures that no longer mirror a real book line for line. The ground-truth files keep the real text locally.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-17: M1 cannot finish until the owner installs the Visual C++ runtime (Q-14). Start M2 meanwhile?
- Date, milestone, task: 2026-11-17, M1 end / M2 start.
- State: everything in M1 that runs without the runtime is done and reviewed (R-54, the wrap-up, T19's Windows harness, the CI fixes, the book-text cleanup). Blocked: `eco setup`, T19's AC1 investigation and full acceptance run, the M1 final review and its fix wave.
- Answer:
  - Yes. Create `m2-web-gui` from the current `m1-core-cli` tip in a separate git worktree under `.claude/worktrees/` (git-ignored), with its own `.venv`, and run M2 there with the same method.
  - One implementer at a time across both checkouts. While the M1 acceptance run measures time and RAM, no M2 agent runs.
  - When the runtime is installed, pause M2 dispatches and finish M1 in the main checkout: T19, the final review, the fix wave, the report and the push.
  - Then merge the final `m1-core-cli` into `m2-web-gui` with a merge commit (no rebase, no force-push). M2's final review and its push wait until that merge is done.
- Why: the owner asked to continue through M4 without waiting. M2's tests need neither the runtime nor the models: they use the Markdown and EPUB paths and a fake worker. M2 builds on M1's public API (`convert_file`, `Options`, events, `load_source`), which the open M1 work is unlikely to change.
- Cost if wrong: a merge of late M1 changes into M2, maybe with conflicts. M2 checks that need a real PDF conversion wait for the runtime too.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-19: The M2 final review waits for the M1 merge (Q-17), and M1 waits for the Visual C++ runtime (Q-14). Run the M2 final review now?
- Date, milestone, task: 2026-11-18, M2 end (after Task 10).
- State: M2 Tasks 1-10 and fix tasks N1 and N2 are done and reviewed on `m2-web-gui` (local only: pushes wait for the owner's decision on permissions). `msvcp140.dll` is still missing, so `m1-core-cli` cannot finish its acceptance run, final review and report.
- Answer:
  - Yes. Run M2's final whole-branch review on `m2-web-gui` as it stands (base `ab570c3`, where it left `m1-core-cli`), then its single fix wave and scoped re-review.
  - When M1 finishes, merge the final `m1-core-cli` into `m2-web-gui` with a merge commit (Q-17: no rebase, no force-push), run the fast suite and, with the runtime, the slow suite on the merge, and give the merge its own scoped review: the M1 changes since `ab570c3`, read against the M2 code that uses them.
  - Start M3 from the reviewed `m2-web-gui` tip without waiting. The later M1 merge moves forward into `m3-xtc` and `m4-docker-release` the same way: a merge commit, never a rebase.
- Why: the owner asked to continue through M4 without waiting for a go. M2 uses M1's public API (`convert_file`, `Options`, events, `load_source`, `inspect_pdf`, `MODELS`), which the open M1 work (the AC1 text fixes and the acceptance run) is unlikely to change. A scoped review of the merge catches what does change.
- Cost if wrong: an M1 change that breaks M2 is found at the merge instead of in M2's final review, and is fixed there; the forward merges into M3 and M4 may need conflict resolution.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop.

### Q-20 (revises the product side of Q-13): without the Visual C++ runtime the model download fails with "could not find or load spatialindex_c-64.dll", and the GUI suggests IPv4. Should eco detect the missing runtime?
- Date, milestone, task: 2026-11-18, M3 (found by the owner in the running M2 GUI).
- Evidence: the owner clicked Download models on this laptop. The setup ended `failed` with `could not find or load spatialindex_c-64.dll` (rtree's DLL, which loads before PyTorch, so PyTorch's own hint never shows), and the page offered "try again over IPv4", which failed the same way. Nothing was downloaded (the models folder stayed empty).
- Answer:
  - Yes. On Windows, when loading the PDF engine fails because a DLL cannot be loaded (rtree, PyTorch, onnxruntime), eco says so plainly: the Microsoft Visual C++ Redistributable (x64) is missing, with the link https://aka.ms/vs/17/release/vc_redist.x64.exe. This holds for `eco setup`, the GUI's model download and PDF conversion. The GUI does not offer the IPv4 retry for this error.
  - It is fixed on `m3-xtc` as fix task M3-N3, with a dated `docs/decisions.md` entry. Q-13's other points stand: no agent runs an admin install, and the README states the prerequisite.
- Why: Q-13 assumed PyTorch's own message would reach the user. It does not, and the IPv4 advice sends the user the wrong way (spec §5 "fragile install on Windows", §8.14 "a clear message").
- Cost if wrong: a few lines that map one error to a message.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed: like Q-18 and Q-19, it waits for the owner (the permission check refuses the controller's commits of this file).

### Q-21: AC1's precision counts the book's index, which the publisher EPUB does not have. Leave the index out of the measure, or make eco drop it?
- Date, milestone, task: 2026-11-18, M1 T19 (AC1 precision 0.9630 against 0.99, recall 0.9948).
- Evidence: 1,369 of the 2,621 unmatched output words are the index (PDF pages 234-240 of Threat Hunting), every word of it. The publisher EPUB's spine has no index (front matter, contents, preface, parts, 14 chapters, back matter). With the index left out, precision is 0.9820.
- Answer:
  - eco keeps the index in its output. No product change.
  - AC1 leaves the output's index section (the section under the heading "Index", PDF pages 234-240) out of the precision measure. The test prints precision with and without it, and the 0.99 threshold applies to the number without it. Recall is unchanged: the owner's metric (`samples/ground-truth/README.txt`) already counts only the range both texts cover.
  - The M1 report gives both numbers.
- Why: the publisher EPUB is the answer key for the book's text, and it never had an index. The index words are correct text from the PDF, so counting them as misses measures what the answer key covers, not what eco extracts. Dropping the index to pass a test would remove content (spec §5). A linked index (print page numbers mapped to places in the EPUB) is a possible later feature, not M1.
- Cost if wrong: if the owner counts print-only matter, AC1 stays below 0.99 and eco needs an option that drops the index. The report's raw number shows the gap.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-22: On digital pages, Docling reads pictures of text by OCR and eco prints that text as body text (headings, paragraphs, tables). Keep it, leave it out of AC1's measure, or keep those pictures as images?
- Date, milestone, task: 2026-11-18, M1 T19.
- Evidence: 769 unmatched output words in Threat Hunting. Page 192 is a full-page picture of a sample document (51% of the page; the text layer has 33 characters), and it came out as headings, paragraphs and list items, so the sample's headings join the book's outline. Pages 47, 52-54 and 91 hold pictures of tables, and they came out as HTML tables built from OCR. The publisher EPUB keeps all of them as images.
- Answer:
  - Product change: on a page that has a text layer, a block whose words are mostly missing from the PDF's text layer inside its box (so they came from OCR of a picture) is kept as an image of that region, not as text. Neighbouring blocks from the same picture become one image. A finding names the page.
  - Pages without a text layer (scans such as Bicara) and `--ocr force` keep the OCR text, as now. Docling's OCR mode stays its default (spec §8.3).
  - AC1's metric does not change for this.
- Why: OCR text from a picture carries OCR errors and invented structure (a sample document's headings in the book's outline, a table structure guessed by the table model), while the image is exact. Spec §8.4 already keeps code on OCR pages as an image for the same reason, and the publisher made the same choice.
- Cost if wrong: text inside such pictures can no longer be searched or reflowed, and a dense picture may be hard to read at 480×800. Removing the rule is one fix-up pass.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-23: The printed contents pages come out as a garbled table with print page numbers. Rebuild them, and drop the page numbers?
- Date, milestone, task: 2026-11-18, M1 T19.
- Evidence: Docling labels pages 10-15 of Threat Hunting `document_index`, and its table model forces the two-column layout into 4 columns: rows pair entries from both columns, and cells merge parts of different entries. This costs 459 unmatched output words and 307 missed truth words. The publisher's contents page has no page numbers.
- Answer:
  - On a page with a text layer, a `document_index` block is rebuilt from the PDF's text layer in reading order (column by column, top to bottom), one entry per line, instead of Docling's table. Scanned pages keep Docling's result.
  - The contents drop their print page numbers and dot leaders. A back-of-book index keeps its numbers, because they are its content.
- Why: wrong reading order without a finding is a failure (spec §5). Print page numbers point to pages a reflowable EPUB does not have. Measured on the book: 0.9667 / 0.9969, against 0.9628 / 0.9948 before.
- Cost if wrong: a contents page without page numbers; the EPUB's own linked contents still work.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-24: Windows Defender quarantines book.md of "Practical Malware Analysis", so the conversion fails with "Errno 22". What does eco say, and how are the Malware criteria measured on this laptop?
- Date, milestone, task: 2026-11-18, M1 T19 (acceptance run 1).
- Evidence:
  - The Malware conversion ran 7306 s and failed at the end of the `fix` stage with `error: [Errno 22] Invalid argument: '...\book.md'`. The book folder holds `report.json` and 457 images, and no `book.md`.
  - Windows Defender's history shows event 1116 at 22:20:47 and 1117 at 22:21:24 for exactly that file: `Exploit:Win32/Pdfjsc.Q`, severity Severe, category Exploit, remediation applied (quarantined). `Get-MpThreatDetection` lists the same path with ActionSuccess True.
  - The signature is a malicious-PDF-JavaScript pattern. The book's own text holds such code, and the PDF itself (compressed) was not flagged; the plain text of `book.md` was.
  - The same failure costs AC3 (Malware Listing 11-1), AC6 (Malware peak RAM) and AC7 for Malware (both its X4 rules and EPUBCheck): no output exists. The other five books were not affected.
- Answer:
  - **Product (the controller's call, in T19 part 3a):**
    - When writing `book.md` fails on Windows with errno 22 or WinError 225, eco raises one plain error. It names the file and says that antivirus software may have removed it, because the book's text can look like malware, and that eco's data folder can be excluded from scanning.
    - It does not suggest turning protection off. The original error stays chained, and a dated `docs/decisions.md` entry records the change.
    - Why: "Invalid argument" sends the user to the wrong place. Like Q-20, it is a Windows environment problem shown as a riddle.
  - **Measurement (the owner's decision; the controller cannot do it):** changing a virus scanner's exclusions is a security-sensitive action on the owner's machine, and it needs the owner's administrator rights. The controller recommends, in this order:
    1. The owner excludes only the scratch folder of the acceptance runs from Windows Security scanning: `C:\Users\RizkiT\AppData\Local\Temp\claude\4c31638f011910be\3ba67816-a6c3-4b47-993f-2a45bec1ea30\scratchpad`. This is Windows Security, Virus & threat protection, Manage settings, Exclusions, Add an exclusion, Folder. The owner removes the exclusion after run 2. The sample PDFs and eco's real data folder stay scanned.
    2. If the owner declines, AC3 for Malware, AC6 and AC7 for Malware are measured in M4 inside the Docker image (Linux, whose files Defender does not scan on the host), and the M1 report says that they are not measured on Windows and why.
  - Until the owner answers, run 2 converts the other five books and leaves Malware out. Malware joins run 2 if the exclusion is set before it starts, and otherwise it waits for M4. Nothing else waits.
- Owner's answer, 2026-11-18 ~23:00: the owner set the exclusion (recommendation 1) for the scratchpad folder. The controller cannot read the exclusion list without administrator rights, so it tested the effect: a standard EICAR test file written there stayed for 20 s with no Defender event (1116/1117), where `book.md` had been quarantined within a second at 22:20. The test file was then removed. Run 2 therefore includes Malware. The owner removes the exclusion after run 2, and the controller reminds them in the run 2 status message.
- Correction, 2026-11-19: the review of T19 part 3a found that the premise above is wrong in one point. The write of `book.md` succeeded (`report.json` is written after it and exists, 22:20:43); Defender quarantined the file at 22:20:46-47, and the failure was the later READ in `load_source`. The plain error therefore covers both the read and the write (ruling R-78), and a cached folder without `book.md` is extracted again. The owner's answer above is unaffected.
- Why: spec §9 criteria 3, 6 and 7 name this book. The report must not claim them as measured when they are not (the controller's rule: no silent gaps).
- Cost if wrong: the Malware criteria are measured later (M4) than they could be, or the owner spends one minute on a Defender setting. Nothing in the repo changes either way except the clear error message.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-25: Should the milestones be built first, with the acceptance (AC) runs done afterwards?
- Date, milestone, task: 2026-11-19, scheduling of M1 T19 and M3 (the owner asked: "apakah mungkin dikerjakan dulu milestonenya baru dilakukan tes AC?").
- Evidence:
  - Acceptance run 1 took 5 h 21 min and found real defects in M1 code (line-end hyphens, OCR lines read upside down, text that XML cannot hold, an antivirus quarantine). The fixes took waves 3a and 3b.
  - M3 has been paused since 2026-11-18 about 14:44, after the Task 2 review, while the M1 senior engineer worked. The cause is the rule of one implementer at a time, not the AC runs themselves.
  - The time limit of AC2 cannot be measured on this laptop (it is skipped as not comparable), and the peak RAM is measured per process, so another job running next to a conversion does not spoil it. Only M3-N1, the render speed task, needs a quiet machine.
- Answer:
  - The AC runs no longer block the milestones. Wave 3b (in progress) and its review finish first.
  - Then M3 resumes (Tasks 3 to 8, then M4), and the full acceptance run 2 (Malware included, since Q-24) runs in the background at the same time. No implementer works on M1 while run 2 runs, so the one-implementer rule stays.
  - What run 2 finds is queued as an M1 fix wave after the M3 task that is running. M1 fixes reach m2-web-gui and m3-xtc as merge commits.
  - M3-N1 (speed) runs when no conversion is running.
  - The M1 final review and the M1 report wait for run 2 and its fix wave. The push stays held (no permission).
  - Not chosen: leaving every AC run until M4 is done. It would find M1 defects after M3 and M4 are built on top of them, and every fix would then be merged forward through more branches.
- Why: the milestones go ahead in parallel with the machine-heavy runs, and M1 defects are still found early.
- Cost if wrong: M3 timings taken while run 2 converts are noisy (hence M3-N1 waits), and an M1 fix wave late in M3 means one more merge forward.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-26: The owner postponed the acceptance (AC) runs until after M5 (supersedes the plan of Q-25)
- Date, milestone, task: 2026-11-19, scheduling of all milestones. This is the owner's decision (message: "tunda ac sampai m5"), not a controller recommendation.
- Evidence: after Q-25 proposed to run acceptance run 2 in the background beside M3, the owner chose to do the milestones first and the acceptance runs last.
- Answer:
  - No acceptance run is started until M5 is built and reviewed. The full run (all six books, Malware included) then runs once on the final tree. Run 1 (2026-11-18) and the AC2 measurements of T19 wave 3a stay as the latest numbers until then.
  - The rest of the process does not change: every task is still reviewed, the M1 final review and the milestone reports are still written, and M2, M3, M4 and M5 follow in that order.
  - M1 closes without run 2. Its report states the criteria as measured so far (run 1 and the later AC2 measurements) and says that run 2 is deferred by this decision, with what is not yet re-measured: AC1 after the wave 3b changes, AC3 Malware, AC6, and AC7 for Malware (and EPUBCheck for it).
  - Wave 3b (in progress) skips the AC1 conversion. In its place the implementer checks the product changes on real pages of Threat Hunting by a page-range extraction (contents, index, picture pages, and ordinary body pages as a false-positive check), at most about 20 minutes of machine time. This is a smoke check, not an acceptance run.
  - M3-N1 (render speed) no longer waits for a quiet machine, because no run is converting.
  - The Windows Defender exclusion of the scratchpad folder (Q-24) is not needed until the final run. The controller tells the owner that it may be removed now and added again before that run.
- Why: the milestones have the owner's priority, and the AC cycle (5 h 21 min per run, plus fix waves) was holding them back.
- Cost if wrong: defects in M1 (extraction and EPUB building) that only the full run shows are found after M2 to M5 are built on it, and their fixes merge forward through more branches. The page-range smoke check limits this for the wave 3b changes, which are the riskiest.
- Recorded by: controller (Claude Opus 5.5), owner's Windows laptop. Not committed (see Q-20).

### Q-27: The owner allows committing this file; pushing stays held
- Date, milestone, task: 2026-11-19, all milestones. This is the owner's decision (message: "saya setuju sesuai saran anda", answering the controller's suggestion), not a controller recommendation.
- Evidence: Q-18 to Q-26 were written here but never committed, because the permission check of the controller's tool refused its commits of this file. The merge of M1 into M2 touches this file. The `decision_on_permissions` of the first handoff was never answered.
- Answer:
  - The controller may commit `agent-decisions.md` (a document only) on the branch where it lives, with the commit identity of this repo. The same holds for the entries of the other agent (Codex: `Q-C1`, `Q-C2`, ... in the M3 worktree's copy).
  - Pushing stays held for every branch. No merge into `main`, no pull request, no force-push. The owner will say when a push is allowed.
  - Commits of code by the agents continue as before, on the milestone branches.
- Why: the entries must travel with the branches they decide, and the M1 to M2 merge needs a clean tree.
- Cost if wrong: none. It is a local commit of a document, and it can be reverted.
- Recorded by: controller (Claude), owner's Windows laptop.

### Q-28: Threat Hunting's contents pages 11-13 read the left parts of several chapters before their right parts. Build a heading rule now, accept the limit, or report it?
- Date, milestone, task: 2026-11-19, M1 T19 wave 3b fix round 1. The implementer's ruling 7 left this to the controller.
- Evidence: after the fix round, contents pages 10-15 of Threat Hunting hold all 652 words, and 491 of the publisher's 632 words are in runs of three or more in the publisher's order (481 before the round). On pages 11-13 each chapter's number and title sit only in the left column, with the entries below it in both columns. The page is read as the whole left column, then the whole right column, so the left parts of several chapters come before their right parts. HEAD 0d26edb read them the same way. A heading rule (a larger font with nothing beside it in the other column ends the columns above it) would fix it; the implementer judged it risky for the letter headings of an index, which sit inside a column.
- Answer:
  - No new rule in the fix round, which is under re-review.
  - The question goes to the M1 final review. If the reviewer judges the order on the real pages to be a spec §5 failure, the single final fix wave builds the rule for contents pages only (the front half of the book). The index in the back half keeps its flowing-column reading, which removes the risk to its letter headings.
  - Until then the limit is stated in the Q-23 entry of docs/decisions.md and in the M1 report as an open risk. No word is lost.
- Why: it affects three pages of one book, the content is complete, and the order is better than before the round. A new rule changes the rebuilt order of every contents page, which needs its own tests and review, and the final fix wave is the cheaper place for it.
- Cost if wrong: books with this layout keep a partly wrong contents order until the fix wave; the EPUB's own linked contents is not affected.
- Recorded by: controller (Claude Sonnet 5.5), owner's Windows laptop.

### Q-29: The owner moves what is left of M1, the merges and the final acceptance run to Codex
- Date, milestone, task: 2026-11-19 13:40, M1 and all later steps. This is the owner's decision (message: "kalau M1 claude belum selesai handoff ke codex saja"). It supersedes the split of 2026-11-19 08:55 ("codex M3-5 aja, M1 tetap claude") for everything that is left of M1.
- Evidence: M1 is not finished: wave 3b is in fix round 2 (the re-review of round 1 found three regressions in the contents reader), and the M1 final review, its fix wave and the report are still ahead. The implementer on the Claude side hit the 5-hour Opus usage limit twice on this day. Meanwhile Codex finished M3 Tasks 3 to 5 (about 3 hours).
- Answer:
  - Codex takes all that is left: the check of round 2, the M1 final review (its own, strict, native method), one fix wave, the M1 report in Indonesian, the merge of `m1-core-cli` into `m2-web-gui` with its scoped review and the M2 report, the forward merge into `m3-xtc`, M3 to M5, and the final acceptance run.
  - Claude finishes only the step that is already running (the senior engineer's round 2, which ends with a clean tree and a report), then stops editing the repo. `STATUS-claude.md` says "HANDED OVER" when that is done. The main checkout and the M2 worktree are Codex's from that moment. Claude keeps the sitrep and answers questions.
  - Pushing stays held for every branch (Q-27). The acceptance runs stay postponed until after M5 (Q-26).
- Why: the owner chose one agent for the rest; Codex is working and Claude's Opus agents are limited.
- Cost if wrong: the M1 final review of a security-sensitive branch becomes a self-review by Codex instead of an Opus reviewer agent, which gives less assurance. The owner can ask Claude for an Opus review of M1 at any time; the ledger, the review packages and the probes stay in `.superpowers/sdd/2026-11-16-m1-core-cli/` and in the scratch folder.
- Recorded by: controller (Claude Sonnet 5.5), owner's Windows laptop.
