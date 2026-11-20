# Guided Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved four-stage Guided Workspace with mandatory expert Review and a separate Export stage.

**Architecture:** Keep the existing server API, job lifecycle, and no-framework single-page workspace. Reshape the template and CSS, then adapt the existing stage and Review state in the current JavaScript modules; common Review sliders remain projections of the existing `review.live.style` object rather than introducing a second style model.

**Tech Stack:** Python 3.12, Starlette/Jinja, browser-native HTML/CSS/ES modules, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-20-guided-workspace-redesign.md`

## Global Constraints

- Preserve conversion algorithms, output formats, preview rendering, and persistence formats.
- Add no dependency and keep the existing HTML/CSS/JavaScript architecture.
- Keep all UI copy in `src/eco/web/strings.py` and in English.
- Keep conversion offline and preserve current API/security behavior.
- Keep one primary action per visible stage and all controls keyboard accessible.
- Review is required before Export; source/result comparison and live sliders remain available.

## Review Focus

- A multi-file job with successful, failed, and cancelled files must allow Export after every successful file is reviewed without requiring failed files.
- Changing a Review slider while a live-preview request is pending must cancel/stale the prior request and render the newest values.
- Focus strength must disappear from keyboard navigation when Focus Mode is off and return with its prior value when enabled.
- Returning from Export must retain the selected file, finding, page, preview format, device view, and unsaved/applied style state.
- Left/right page shortcuts must not fire while a slider, input, select, button, or link has focus.

---

## File structure

- Modify `src/eco/web/templates/index.html`: four stage surfaces, Guided Select hierarchy, mandatory Review controls, and Export markup.
- Modify `src/eco/web/static/app.css`: Guided Workspace geometry, Review dock, Export layout, responsive and focus states.
- Modify `src/eco/web/static/app.js`: four-stage definitions, focus routing, stage links, and shared event wiring.
- Modify `src/eco/web/static/start.js`: merge the visible Settings step into Select without changing option serialization.
- Modify `src/eco/web/static/review.js`: review tracking, common live controls, approval gate, Export rendering, and state retention.
- Modify `src/eco/web/static/job.js`: transition completed jobs into mandatory Review rather than download-oriented completion.
- Modify `src/eco/web/strings.py`: all Guided Workspace and Export copy.
- Modify `tests/web/test_app.py`: static contract and accessibility tests for the new workspace.
- Modify `tests/web/test_preview.py` only if live-preview request behavior needs a server contract assertion.

### Task 1: Four-stage shell and Select/Convert hierarchy

**Files:**
- Modify: `src/eco/web/templates/index.html`
- Modify: `src/eco/web/static/app.css`
- Modify: `src/eco/web/static/app.js`
- Modify: `src/eco/web/static/start.js`
- Modify: `src/eco/web/static/job.js`
- Modify: `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: existing `setStage(name)`, `showSelect(part)`, `showProcessing()`, job state, and option serialization.
- Produces: stage names `select`, `processing`, `review`, `export`; Select still serializes the existing options schema.

- [ ] **Step 1: Add failing static-contract tests**

Add tests asserting the step copy/order is Select, Convert, Review, Export; Settings is not a separate step; Select retains all existing option element IDs; and each non-setup stage has exactly one visible primary workflow action in its initial markup.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run pytest tests/web/test_app.py -k "step or guided or primary" -q`
Expected: FAIL on missing Export stage and old step names.

- [ ] **Step 3: Implement the shell and copy**

Update the stage definitions and focus routing in `app.js`, keep Settings controls inside `stage-select`, reshape Select and Processing markup/CSS to the approved hierarchy, and add exact copy to `STRINGS`.

- [ ] **Step 4: Run the focused tests**

Run: `uv run pytest tests/web/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eco/web/templates/index.html src/eco/web/static/app.css src/eco/web/static/app.js src/eco/web/static/start.js src/eco/web/static/job.js src/eco/web/strings.py tests/web/test_app.py
git commit -m "feat: add guided workspace shell"
```

### Task 2: Expert Review dock and mandatory approval

**Files:**
- Modify: `src/eco/web/templates/index.html`
- Modify: `src/eco/web/static/app.css`
- Modify: `src/eco/web/static/review.js`
- Modify: `src/eco/web/static/app.js`
- Modify: `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `review.live.style`, `scheduleLivePreview()`, `refreshDevice()`, existing finding/page/format/view state, and rebuild requests.
- Produces: `review.reviewed: Set<number>`, `reviewDockDirty() -> boolean`, `syncReviewDock() -> void`, and `approveCurrentFile() -> Promise<void>`.

- [ ] **Step 1: Add failing Review contract tests**

Assert the main Review surface contains labeled range inputs for `style-font-size`, `line-height`, `margin-x`, and `first-line-indent`, plus `focus-mode` and `focus-strength`; source and device panes remain peers; focus strength is conditionally disabled/hidden; and advanced settings reuse the same style state without duplicate IDs.

- [ ] **Step 2: Add failing behavior-source tests**

Assert slider `input` events update `review.live.style` and schedule the existing debounced preview, pending live requests are aborted, arrow paging ignores interactive targets, approval records only successful files, and mixed failed/cancelled files do not block eligibility.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `uv run pytest tests/web/test_app.py -k "review or focus or preview or arrow" -q`
Expected: FAIL on the old settings panel and missing approval state.

- [ ] **Step 4: Implement the shared dock**

Move the named controls into the dock, keep other style controls in Advanced typography, bind all controls to `review.live.style`, show Focus strength only while enabled, and preserve the existing debounce/abort semantics.

- [ ] **Step 5: Implement mandatory per-file approval**

Track reviewed successful file indices, expose reviewed/unreviewed state in the file picker, require pending changes to be applied or reset before approval, and enable Export only when every successful file is reviewed.

- [ ] **Step 6: Run Review tests**

Run: `uv run pytest tests/web/test_app.py tests/web/test_preview.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/eco/web/templates/index.html src/eco/web/static/app.css src/eco/web/static/review.js src/eco/web/static/app.js src/eco/web/strings.py tests/web/test_app.py tests/web/test_preview.py
git commit -m "feat: make expert review mandatory"
```

### Task 3: Export stage and retained navigation state

**Files:**
- Modify: `src/eco/web/templates/index.html`
- Modify: `src/eco/web/static/app.css`
- Modify: `src/eco/web/static/review.js`
- Modify: `src/eco/web/static/app.js`
- Modify: `src/eco/web/strings.py`
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `review.reviewed`, current job files/outputs/findings, existing download URLs, and delete flow.
- Produces: `showExport() -> void`, `renderExport() -> void`; Back to Review preserves the existing `review` object unchanged.

- [ ] **Step 1: Add failing Export tests**

Assert Export has validation/status text, one download link per available output, a Back to Review action, low-emphasis deletion, no download links in the Review toolbar, and a guard that redirects unreviewed jobs to Review.

- [ ] **Step 2: Add state-retention tests**

Assert `showExport()` does not clear Review page/file/finding/format/view/style state and Back to Review calls the normal Review render path without reinitializing the job.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `uv run pytest tests/web/test_app.py -k "export or download or review" -q`
Expected: FAIL because downloads still live in Review and Export does not exist.

- [ ] **Step 4: Implement Export**

Add the stage markup and renderer, move download presentation out of Review, retain existing safe server download URLs, add the approval guard, and preserve Review state on return.

- [ ] **Step 5: Run focused web tests**

Run: `uv run pytest tests/web/test_app.py tests/web/test_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eco/web/templates/index.html src/eco/web/static/app.css src/eco/web/static/review.js src/eco/web/static/app.js src/eco/web/strings.py tests/web/test_app.py
git commit -m "feat: add reviewed export stage"
```

### Task 4: Responsive/accessibility polish and full verification

**Files:**
- Modify: `src/eco/web/static/app.css`
- Modify: `src/eco/web/static/app.js`
- Modify: `src/eco/web/static/review.js`
- Modify: `tests/web/test_app.py`
- Modify: `docs/qa/m2-gui-checklist.md`

**Interfaces:**
- Consumes: completed four-stage workflow.
- Produces: no new runtime interface; closes responsive, keyboard, state, and QA requirements.

- [ ] **Step 1: Add accessibility and responsive contract tests**

Assert every Review slider has a label/output pair, disabled Focus strength is removed from keyboard use, statuses are not color-only, coarse-pointer controls keep 44 px targets, the narrow Review layout stacks source before result, and the step navigation cannot cover content.

- [ ] **Step 2: Run tests and verify any remaining failures**

Run: `uv run pytest tests/web/test_app.py -q`
Expected: FAIL only for missing final accessibility/responsive rules.

- [ ] **Step 3: Complete CSS and keyboard behavior**

Implement desktop, medium, and phone Review layouts; preserve visible focus and reduced motion; make page shortcuts ignore every interactive element; and keep dynamic status text announced without excessive live updates.

- [ ] **Step 4: Update the GUI QA checklist**

Add the four-stage path, mandatory multi-file Review, live dock controls, Focus toggle/strength, Export/back navigation, desktop/phone layouts, keyboard-only flow, and mixed-status job checks.

- [ ] **Step 5: Run complete verification**

Run: `uv run pytest`
Expected: all fast tests pass.

Run: `uv run ruff check`
Expected: no violations.

Run: `uv run ruff format --check`
Expected: no files require formatting.

- [ ] **Step 6: Commit**

```bash
git add src/eco/web/static/app.css src/eco/web/static/app.js src/eco/web/static/review.js tests/web/test_app.py docs/qa/m2-gui-checklist.md
git commit -m "test: verify guided workspace redesign"
```

## Self-review

- Spec coverage: all four stages, mandatory multi-file Review, common controls, Focus behavior,
  side-by-side comparison, Advanced typography, Export, responsiveness, accessibility, and
  verification map to Tasks 1-4.
- Step scan: each task has a failing-test, implementation, passing-test cycle and one reviewable
  deliverable.
- Type consistency: the only new shared state is `review.reviewed`; Export consumes it unchanged.
- Review Focus: each listed risk has an explicit test in Task 2, 3, or 4.
- Proportion: the plan specifies interfaces and assertions without transcribing implementation.
