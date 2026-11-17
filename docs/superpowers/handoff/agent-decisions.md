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

## Answers recorded on the new machine

(append below)
