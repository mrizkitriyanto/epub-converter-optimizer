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
