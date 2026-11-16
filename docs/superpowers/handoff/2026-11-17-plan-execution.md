# Execution Handoff: eco Plans M1–M4

- Date: 2026-11-17
- Status: the design is approved and all four plans are written. **Nothing is implemented yet.**
- Rule: **do not start until the owner explicitly says so.**

## Read first

| What | Where |
|---|---|
| Spec (Indonesian, approved) | `docs/superpowers/specs/2026-11-16-epub-converter-optimizer-design.md` |
| Plan M1: core + CLI (19 tasks) | `docs/superpowers/plans/2026-11-16-m1-core-cli.md` |
| Plan M2: web GUI + preview (10 tasks) | `docs/superpowers/plans/2026-11-16-m2-web-gui.md` |
| Plan M3: XTC/XTCH + page style (8 tasks) | `docs/superpowers/plans/2026-11-16-m3-xtc.md` |
| Plan M4: Docker + release (4 tasks) | `docs/superpowers/plans/2026-11-16-m4-docker-release.md` |
| Research and spike evidence | `docs/research/2026-11-16-references.md`, `docs/research/2026-11-16-spike-pdf-engines.md` |
| Approved GUI layout | `docs/design/gui-layout.html` |
| Local only, owner's machine, never commit | `samples/` (copyrighted books), `samples/ground-truth/` (acceptance answers, see its `README.txt`), `samples/public/arxiv-1512.03385v1.pdf` |

## Binding owner decisions

- **Execution method:** subagent-driven (`superpowers:subagent-driven-development`), chosen by the owner on 2026-11-17.
- **One milestone at a time, in order M1 → M2 → M3 → M4.** After a milestone's final whole-branch review, stop, report to the owner, and wait for the owner's go before the next milestone.
- **Language:** talk to the owner in **Indonesian**. Write code, comments, commit messages, UI text and new docs in **English**. The README exists in two languages. The spec and research notes stay in Indonesian.
- **Plugins:** follow ponytail and antislop. antislop requires `DESIGN.md` before any UI work; M1 Task 3 creates it with style B ("neutral and clean").
- **Downloads:** before any download larger than 50 MB (AI models are ~568 MB, Docker images several GB), state the measured size and wait for a yes.
- **Device testing is deferred.** Values marked "verify on device" stay provisional and are logged in `docs/decisions.md`.
- **Repo:** public on GitHub, MIT license. The git identity is set in the repo config to the owner's GitHub noreply address; do not change it.
- **Never commit** `samples/`, any book file, or any `*.pdf|*.epub|*.xtc|*.xtch` outside `tests/fixtures/`. **Never overwrite** an input file.
- **Commits** happen per task on the milestone branch. **Push and open a PR only when the owner asks.**

## Role map

These are the owner's agent-team rules. Use this table if your environment does not already load them. Pass model and effort explicitly on every dispatch, and never use fable.

| Role | Agent | Model / effort | Applies to |
|---|---|---|---|
| Implementer | `junior-engineer` | sonnet, high | default |
| Implementer, integration task | `junior-engineer` | sonnet, max | M1 T6, T8, T11, T17; M2 T6, T7, T9; M3 T2, T6, T7 |
| Implementer, concurrency/security/infra task | `senior-engineer` | opus, xhigh | M1 T10 (model download allowlist), M2 T4 (worker processes), M2 T5 (token auth), M4 T2–T3 (Docker, release) |
| Blocked task; fix rounds 4–5 | `senior-engineer` | opus, xhigh, then opus max on a second escalation | any |
| Task review | `reviewer` | sonnet high for a small mechanical diff, otherwise opus high | every task |
| Final whole-branch review | `reviewer` | opus max for M1 (data integrity, privacy) and M2 (security); opus xhigh for M3 and M4 | each milestone |

Escalation path: junior-engineer (if it reports NEEDS_CONTEXT, the same agent with more context) → senior-engineer xhigh → senior-engineer max → park the task with a ruling in the ledger. Around every review, run `git status --porcelain` and `git diff --stat` before and after. If a review changed the working tree, stop and tell the owner. A second opinion from another model family is the owner's call.

If your harness has no superpowers skills (for example another agent at another endpoint), execute the tasks in order with each task's TDD steps, and have an independent reviewer check every task before the next one starts.

## Branches

- One branch per milestone, created in a worktree with `superpowers:using-git-worktrees`: `m1-core-cli`, `m2-web-gui`, `m3-xtc`, `m4-docker-release`.
- Each milestone starts from `main` after the previous milestone is merged.
- Finish with `superpowers:finishing-a-development-branch`. The owner decides between merge and PR.

## Pre-flight (before the first task of a milestone)

1. `git status` is clean on `main`; `uv --version` is ≥ 0.13.
2. At least 5 GB of free disk and 8 GB of RAM.
3. Network quirks seen on the owner's network:
   - IPv6/NAT64 resets TLS connections, and Hugging Face's `hf-xet` downloader stalls.
   - Use `eco setup --ipv4`, keep `HF_HUB_DISABLE_XET=1`, and expect Hugging Face speeds of 125 KB/s–1.4 MB/s.
   - PyPI is fast.
4. M1 Task 11 and later need the models (`eco setup`, ~568 MB). Ask the owner first.
5. M1 Task 19 (acceptance) runs only where `samples/` exists, which is the owner's Mac; it is skipped elsewhere.

## Verified facts the plans rely on

| Topic | Fact |
|---|---|
| Docling 2.150.1 | `convert(source, page_range=(a, b), progress_callback=cb)` emits `PageCompletedProgress(page_no, completed_pages, total_pages)` |
| | `RapidOcrOptions(mode=...)` exists |
| | `docling.utils.model_downloader.download_models(output_dir, progress, with_layout, with_tableformer, with_code_formula, with_picture_classifier, with_rapidocr, ...)` |
| | It does **not** install `onnxruntime`; the project lists it explicitly |
| | Its CLI is now `docling convert` |
| pypdfium2 5.15 | `get_toc()` → `PdfBookmark.get_title()`, `.level`, `.get_dest().get_index()` |
| | `PdfTextPage.get_charbox(i)`, `get_text_bounded()` |
| | `PdfPage.get_cropbox()` / `set_cropbox()` |
| typst-py 0.15 | `typst.compile(files, format="png", ppi=72.0, ignore_system_fonts=True, font_paths=[...])` returns `list[bytes]` |
| | `typst.query(files, "<label>", field="value")` returns JSON |
| | `typst.Fonts(font_paths=[...]).families()` |
| XTC format | follow CrossPoint's reader (`lib/Xtc/Xtc/XtcTypes.h`, `XtcParser.cpp`); exact rules in the M3 plan's Global Constraints |
| Spike gotchas | add the CropBox offset when re-extracting code; keep OCR in default mode (full-page OCR damages italics); Marker was rejected (crashes on blank pages, no code blocks or images); details in the spike note |

## Prompts to start (the owner pastes one when ready)

**M1**

```
Execute milestone M1 of eco with superpowers:subagent-driven-development.

Read first, in order:
1. docs/superpowers/handoff/2026-11-17-plan-execution.md (binding rules, role map, pre-flight)
2. docs/superpowers/plans/2026-11-16-m1-core-cli.md (the plan to execute)
3. docs/superpowers/specs/2026-11-16-epub-converter-optimizer-design.md (the spec, in Indonesian)

Run the pre-flight checks from the handoff, create branch m1-core-cli in a worktree, then execute the plan task by task using the handoff's role map. Ask me before any download larger than 50 MB. Talk to me in Indonesian. When M1's final whole-branch review is done, stop and report; do not start M2 until I say so.
```

**M2, M3, M4.** Use the same prompt with these substitutions, and add the line `The previous milestone must already be merged into main.`

| Milestone | Plan | Branch |
|---|---|---|
| M2 | `docs/superpowers/plans/2026-11-16-m2-web-gui.md` | `m2-web-gui` |
| M3 | `docs/superpowers/plans/2026-11-16-m3-xtc.md` | `m3-xtc` |
| M4 | `docs/superpowers/plans/2026-11-16-m4-docker-release.md` | `m4-docker-release` |
