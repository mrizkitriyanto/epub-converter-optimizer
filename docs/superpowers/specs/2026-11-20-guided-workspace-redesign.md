# Guided Workspace redesign

Date: 2026-11-20

## Intent

Redesign the complete local web GUI around one guided workspace. A new user should be able to
start a conversion without understanding EPUB internals, while Review remains a required,
powerful checkpoint before download. The redesign must improve hierarchy and wording without
removing the conversion, preview, style, saved-style, font, job, or validation capabilities that
already exist.

## Goals

- Use four visible stages: Select, Convert, Review, and Export.
- Keep one primary action in each stage.
- Make Select approachable with device and output choices visible and specialist settings
  collapsed.
- Keep detailed conversion progress and findings understandable.
- Make Review mandatory before Export.
- Preserve the original/result side-by-side comparison and synchronized finding navigation.
- Put the most-used reading controls directly below the Review comparison as live sliders.
- Keep the full expert style editor available without crowding the main Review workspace.
- Give downloads and validation status a dedicated Export stage.
- Preserve keyboard operation, visible focus, responsive layouts, and current local-only wording.

## Non-goals

- Changing conversion algorithms, output formats, preview rendering, or persistence formats.
- Adding accounts, cloud storage, analytics, or network access during conversion.
- Replacing the existing no-framework HTML, CSS, and JavaScript stack.
- Introducing a new component or icon dependency.
- Redesigning the CLI.

## Anti-goals

- A dashboard full of cards before the user can start.
- Hiding expert Review controls behind several dialogs.
- Removing source/result comparison or reducing Review to a download screen.
- Automatically applying expensive rebuilds for every slider movement.
- Making progress or status understandable only through color.

## Selected approach

### Guided Workspace

The existing single-workspace architecture remains. Its visible stages become Select, Convert,
Review, and Export. This reuses the current stage/state model and minimizes risk while giving the
workflow a clearer beginning, checkpoint, and finish.

Review is the deliberate exception to the novice-first surface: it is designed for a power user.
The source, output preview, findings, page navigation, output format, and device view remain
available together. Common reading controls stay on the main surface.

### Alternatives considered

- **Task-focused:** full-screen task pages with a permanent Review inspector. It gives Review more
  space, but requires a larger structural rewrite and makes movement between tasks less coherent.
- **Book Studio:** persistent project sidebar and build history. It suits repeated multi-build work,
  but adds navigation and state that are unnecessary for the current job-based product.

Guided Workspace was selected because it improves the entire workflow while retaining the proven
single-page stage model.

## Information architecture

### 1. Select

- Heading and short description explain the task.
- File drop area and selected-file details occupy the left panel.
- Device, outputs, and quality occupy the right panel.
- Firmware, OCR, layout, metadata, initial Focus Mode, and the font library remain in collapsed
  details.
- Recent conversions remain below the main panels.
- Primary action: **Start conversion**.

The current Settings step is absorbed into Select. The stepper therefore has four stages rather
than treating file selection and settings as separate steps.

### 2. Convert

- Show the current file, overall percentage, current page, and estimate.
- Show conversion stages with explicit done/current/waiting text and marks.
- Show findings accumulated so far in a parallel panel.
- Preserve cancellation and queued multi-file behavior.
- On completion, move to Review; do not expose download as the next action.

### 3. Review

Review is required for every successfully converted file.

The top bar contains the file title, output summary, reset/change status, and the primary action
**Approve and continue**. Multi-file selection remains available.

The main workspace has three columns on wide screens:

1. Findings list.
2. Original source page or source text.
3. Device/output preview.

The original and result remain side by side. Clicking a finding keeps both previews synchronized.
Page navigation, keyboard arrows, device view, and EPUB/XTC selection remain available.

The main control dock contains:

- Text size slider.
- Line spacing slider.
- Horizontal page margin slider.
- Paragraph first-line indentation slider.
- Focus Mode toggle.
- Focus strength slider, visible and enabled when Focus Mode is on.

Slider movement updates the live preview using the existing debounced live-preview request. It
does not rebuild output files. Changed controls show a dirty state. The user applies/rebuilds once
through the Review action before approval where required by the existing output behavior.

The expert editor remains available as **Advanced typography**. It contains saved styles, font and
weight, vertical margins, paragraph spacing, alignment, hyphenation, language, image/color
settings, progress-bar settings, orientation, quality, style save/default/delete, and style JSON
copying. Controls promoted to the dock must not be duplicated as two independent values; both
surfaces edit the same state.

For EPUB-only Focus Mode changes, the existing Focus apply behavior is folded into the shared
Review state so the user does not encounter two competing Apply buttons.

### 4. Export

Export appears only after Review approval. It shows:

- Validation outcome, including EPUBCheck warnings or failures.
- File name, output format, and file size for every generated output.
- A download action for each available file.
- A route back to Review without re-reading the source PDF.
- Delete conversion as a low-emphasis destructive action.

Primary action: download the main output, or download selected outputs when multiple formats are
present.

## State and behavior

- The server API and job lifecycle remain the source of truth.
- Existing URLs and preview endpoints remain unchanged unless implementation proves a small API
  adjustment is necessary for approval state.
- Review approval is client workflow state; it does not claim that content is semantically
  correct. Export is reachable only after the current file has been shown in Review and pending
  style changes have been applied or discarded.
- Returning from Export to Review retains page, selected finding, preview format, view, and control
  values.
- Multi-file jobs require reviewing each converted file. The UI clearly marks reviewed and
  unreviewed files; Export becomes available when all successful outputs have been reviewed.
- Failed or cancelled files remain inspectable and do not block Export of successfully reviewed
  files.
- Loading, empty, error, disabled, dirty, applying, and success states must be visible in text.

## Responsive behavior

- Desktop Review keeps findings, source, and result in one row when space permits.
- At medium widths, findings become a horizontal/compact region while source and result remain
  side by side.
- At phone widths, the comparison stacks source before result and the control dock becomes a
  vertical group. No control or preview is clipped horizontally.
- Touch targets are at least 44 by 44 pixels on coarse pointers.
- The stage navigation wraps or becomes horizontally scrollable without covering content.

## Accessibility

- Preserve native buttons, links, labels, inputs, fieldsets, and headings.
- Every slider has a visible label, current value, and keyboard support.
- Focus strength is disabled and hidden from keyboard navigation when Focus Mode is off.
- Status, warning, dirty, and completion states use text or icons in addition to color.
- Dynamic preview and apply states use appropriate polite live regions; actionable errors use
  alerts.
- Source and result DOM order matches their visual order.
- Existing left/right page keys must not interfere while a slider, input, or select is focused.
- Reduced-motion behavior remains supported.

## Visual direction

- Retain the current neutral light palette, system font, blue accent, 6 px control radius, and
  10 px panel radius from `DESIGN.md`.
- Use borders and spacing for structure; avoid additional decorative cards and shadows.
- Keep a single high-emphasis action per stage.
- Use plain English throughout the product UI.

## Implementation boundaries

Likely production files:

- `src/eco/web/templates/index.html`: stage and Review/Export structure.
- `src/eco/web/static/app.css`: Guided Workspace layout and responsive behavior.
- `src/eco/web/static/app.js`: stage mapping and event wiring.
- `src/eco/web/static/start.js`: Select behavior where Settings is merged into the first stage.
- `src/eco/web/static/job.js`: Convert presentation, without changing job semantics.
- `src/eco/web/static/review.js`: mandatory Review, shared live controls, approval, and Export.
- `src/eco/web/strings.py`: all new or revised English UI text.
- Existing web tests, especially `tests/web/test_app.py`, `test_jobs.py`, `test_preview.py`, and
  render/style tests where their contracts are touched.

The implementation should reuse existing IDs and functions when practical. New abstractions or
dependencies are not justified.

## Verification

- Run focused web and style tests while implementing.
- Run the full fast test suite and Ruff before completion.
- Exercise the four-stage flow with at least Markdown and PDF fixtures.
- Verify multi-file Review gating, failed/cancelled files, existing saved styles, Focus Mode,
  EPUB/XTC format switching, and returning from Export to Review.
- Check desktop and narrow layouts, keyboard navigation, visible focus, live slider updates, and
  reduced motion.

## Builder self-check

The specification keeps existing conversion and API behavior, identifies the client files that
own each stage, defines the mandatory Review gate and multi-file rule, and resolves the main
potential ambiguity: sliders preview changes live but do not trigger a rebuild on every movement.
Minor implementation choices such as exact breakpoint values and debounce timing remain with the
builder and should follow existing CSS and JavaScript patterns.
