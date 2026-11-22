# Library names for downloads

Date: 2026-11-22. Size: small change. Status: approved approach, design awaiting approval.

## Intent

The owner downloads converted books with names such as
`IND_Never_Split_The_Difference_Chris_Voss_V5_5.x4-pro.epub`. A toggle in Export renames each
download to `Language - Title - Author`, with all three found by the program. The owner keeps a
language prefix in their own file names, so the language comes first.

## Goals

- A toggle in Export, on or off, applies to every download button of the job.
- The name: `<LANG> - <Title> - <Author>.epub`, and `<LANG> - <Title> - <Author>.<device>.<ext>` for
  XTC and XTCH. Example: `ID - Never Split the Difference - Chris Voss.epub`,
  `ID - Never Split the Difference - Chris Voss.x4-pro.xtch`. The EPUB has no device ending because
  it reflows on any reader; an XTC fits one screen size (X3 is 528x792, the X4 family 480x800).
- `LANG` is the two-letter ISO code in capitals (`ID`, `EN`), detected from the book's text.
  Metadata is not trusted: two of the owner's Indonesian books say `en`.

## Non-goals

- The CLI keeps today's names (`output_path`). Agent's call; the owner can ask for a flag later.
- Jobs converted before this change keep their old names; the toggle does nothing for them.
- Telling apart a Xteink EPUB and a general EPUB of the same book by name.

## Approaches

1. **Compute at conversion, store in the job (picked by the owner).** The pipeline already holds the
   metadata and the text. It works out language, title and author once, the job stores them, and the
   download route uses them when asked. Download stays instant; EPUB and XTCH of one book share a
   name. Old jobs are not covered.
2. Compute at download: open the output EPUB, read its metadata and text each time. Covers old
   jobs, but every download reads the whole book first, and an XTCH-only job has no text to read.
3. Browser-only rename with the `download` attribute: dropped. The server's `Content-Disposition`
   wins over the attribute, and language detection lives in Python.

## Design

**Parts of the name** (one pure function, its own tests):

- Language: `detect_language` on the book's text, extended so it can say "neither" when the text
  has too few English or Indonesian stopwords. Then the metadata language's primary subtag is used
  (`ja-JP` -> `JA`); with none, the language part is left out.
- Title: the metadata title, HTML entities decoded, whitespace collapsed.
- Author: the first `dc:creator`.
  - `Last, First` (one comma, no " and ") becomes `First Last`: `Covey, Stephen` -> `Stephen Covey`.
  - Several authors (a list, or a single string joined by `,`, ` and `, `&`) give the first one
    plus ` dkk.` if the book is Indonesian, ` et al.` otherwise.
  - No author, and a title that ends in ` - <Name>`: the name moves to the author.
    `Bicara itu ada seninya - Oh Su Hyang` -> title `Bicara itu ada seninya`, author `Oh Su Hyang`.
  - Still no author: the author part is left out (`ID - Title.epub`).
- Safe for Windows: `: ? / \ * " < > |` and control characters become ` - ` for a colon and are
  dropped otherwise; repeated spaces and dashes collapse; trailing dots and spaces go; a reserved
  name (`CON`, `NUL`...) gets a suffix. The whole name is capped (about 150 characters before the
  extension), cutting the title at a word.
- Title and author the user typed in the options win over the book's own (as `_override` does).

**Where it runs:** at the end of `convert_file`, from the source the pipeline has (the book meta and
markdown for PDF, Markdown and the XTC path; for an EPUB-only run, text gathered from the XHTML
bodies the optimizer already parses, a sample is enough). `Result` and `JobFile` gain
`library_name: str | None` (the name without extension); `None` for old jobs and failed files.

**Download:** `GET /api/jobs/{id}/files/{n}/download/{fmt}?name=library` sends
`Content-Disposition` with the library name plus the ending above, through `_disposition`. Without
the parameter, or with no stored name, today's name.

**Export screen:**

```
Ready to download
[x] Name files as Language - Title - Author
    ID - Never Split the Difference - Chris Voss
    EPUB · Reflowable · 490 KB ...              [Download EPUB]
```

- The toggle sits above the file list; each row shows the name it will download under while the
  toggle is on. Agent's call: seeing the name lets the owner catch a wrong detection before
  downloading.
- The choice is remembered in the browser (`localStorage`, wrapped in try/catch), off on first use.
  Agent's call: off keeps today's behaviour until the owner turns it on once.
- New strings go in `STRINGS`, in English.

## Left to the builder

The exact stopword threshold for "neither", the name cap, and how the optimizer hands its text
sample back to the pipeline.
