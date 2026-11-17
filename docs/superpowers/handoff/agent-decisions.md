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
