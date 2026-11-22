# Language code in the book title

Date: 2026-11-22. Size: small change. Status: approach picked by the owner, design awaiting approval.

## Intent

The title a reader shows in its library should carry the language, the same way the download name
does: `ID - Deep Work`, `EN - The Foundations of Threat Hunting`. It is always on, with no toggle.
The book's own language field is corrected at the same time, because many of the owner's
Indonesian translations say `en`.

## Goals

- Every converted EPUB gets `dc:title` = `<CODE> - <title>`. The code comes from the same detection
  as the download name (`eco.naming`: the text's English or Indonesian stopwords, else the metadata's
  primary subtag, else none). With no code, the title is left as it is.
- `dc:language` is set to the detected language (`id` or `en`) when the text decided it. When only
  the metadata gave a code, `dc:language` stays as it is (it keeps a region such as `ja-JP`).
- The XTC and XTCH header title and language follow the same rule.
- A title that already starts with `<CODE> - ` for the same code (an eco output converted again) is
  not prefixed twice. The download name drops that prefix before it builds `CODE - Title - Author`,
  so it never reads `ID - ID - ...`.

## Non-goals

- No toggle, no CLI flag.
- The NCX `docTitle`, the nav title and the title page keep their text.
- The Title option still does not rename an EPUB input's `dc:title` (as today); it only feeds the
  download name and the XTC title, as before.

## Approaches

1. **Detect before optimize, the optimizer writes the OPF (picked by the owner).** `convert_file`
   builds the book facts once, before the optimizer runs, and passes the code and the detected
   language in. The optimizer edits `dc:title` and `dc:language` while it already holds the OPF;
   `_write_xtc` uses the same values. One write per file; one detection for title, language and
   download name.
2. Patch the finished EPUB: reopen it after optimize, edit the OPF, write the zip again. Leaves the
   optimizer alone, but writes every book twice (slow on a 33 MB book) and still needs the XTC
   handled apart.

## Design

- `eco/naming.py` gains `language_code(facts) -> tuple[str, str | None]` (the code for the title,
  `""` for none; the detected language, `None` when the text did not decide) and
  `titled(title: str, code: str) -> str`. `library_name` uses both, so the three outputs agree.
- `convert_file` builds the facts at the start, with the same rules as `_library_name` today (EPUB
  input from its OPF and spine; other inputs from the book source; PDF and book folders take only
  the Language option). A failure gives no code: the conversion goes on unchanged.
- `optimize_epub(src, dst, options, code="", language=None)`: prefixes the first `dc:title` with
  `titled`, sets the first `dc:language` (adds one if there is none) when `language` is given.
- Agent's call: the optimizer also sets `dcterms:modified` (EPUB 3) to the conversion time, so a
  reader that caches by book sees that the file changed. EPUB 2 packages are left as they are.
- Every device, not only Xteink: the title is metadata, not layout.

## Left to the builder

How the code and language reach the optimizer and `_write_xtc` (parameters or a small dataclass),
and the test fixtures.
