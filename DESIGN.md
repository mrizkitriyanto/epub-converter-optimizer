# DESIGN.md

Visual rules for the eco web GUI: the page map redesign. Read this before any UI work.
The design spec is `docs/superpowers/specs/2026-11-20-end-to-end-redesign-design.md`; this file
holds the values.

## Tokens

| Token | Value | Use |
|---|---|---|
| Background | `#FAFAF9` | page |
| Panel | `#FFFFFF` | panels, header, inputs |
| Border | `#E4E4E7` | panel borders, row dividers |
| Control border | `#D4D4D8` | secondary buttons, segmented controls |
| Control edge | `#8A8A93` | edges of inputs and selects (3 : 1) |
| Text | `#18181B` | body text |
| Muted | `#52525B` | secondary text |
| Subtle | `#71717A` | hints, waiting states |
| Accent | `#1D4ED8` | primary button, current page, in-progress stage, links |
| Success | `#15803D` | "Done" text and marks |
| Warning text | `#B45309` | finding labels |
| Warning mark | `#F59E0B` | finding squares and bars (graphic only, never text) |
| Error | `#B91C1C` | failure text, destructive action |
| Page done | `#3F3F46` | page map |
| Page waiting | `#E4E4E7` | page map |
| Page scanned | `#6D28D9` | Select page map |
| Page digital | `#D4D4D8` | Select page map, Review strip |
| Device bezel | `#262626` | device preview |
| E-ink screen | `#E9E9E4` | device preview |

## Type

- Font: Inter (variable, bundled in `src/eco/web/static/fonts/`, OFL). Fallback:
  `"Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif`.
- Base 14px, line height 1.5. Screen titles 26–28px weight 600. Large figures 36–44px weight 500.
  Labels and hints 12–13px. Changing numbers use tabular figures.

## Radii

- Controls: 8px
- Panels: 10px
- Page squares: 2px

## Rules

- One primary (blue) button per screen.
- Plain English copy. No hype, no emoji.
- Advanced settings stay collapsed.
- Status is never color-only: every state has a word.
- The page map is the shared picture of progress: squares on Select and Convert, a strip in Review.
- Structure comes from borders and spacing: no shadows, gradients or colored left borders.
- Touch targets at least 44 by 44 px.
- Nothing loads from the network, fonts included.
- Light theme only.
