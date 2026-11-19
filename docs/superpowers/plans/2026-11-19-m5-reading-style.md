# M5 reading style implementation

Approved design: `docs/superpowers/specs/2026-11-19-m5-reading-style-design.md`. Work on `m5-reading-style` from M4. Keep each change small and test it before moving on.

1. Freeze M3's default XTC render as page hashes. Verify it before changing style code.
2. Extend `PageStyle` with center alignment, split margins, paragraph spacing and indent. Migrate stored `margin` to both axes. Keep default render hashes unchanged; test each new control with rendered pages.
3. Add Focus Mode to XTC body text, with Latin, Greek and Cyrillic grapheme handling, three strengths and font weight checks. Verify text identity, exclusions, hyphenation, layout and speed against the approved limits.
4. Add a font library under `<data>/fonts` with validated upload, listing, deduplication, replacement and deletion. Wire CLI and web API. Keep existing job fonts readable. Test fallback findings after deletion.
5. Add saved styles and default style in `<data>/styles` and `settings.json`. Wire CLI, new jobs and the panel, with strict input and lenient stored state.
6. Add missing-character checks to XTC conversion and live preview, with count and sample characters.
7. Update GUI controls, English and Indonesian docs, the decision log and manual checklist. Run full tests, lint, exact preview checks and the final acceptance suite with isolated data. Record device and macOS checks separately when hardware is available.
