# AGENTS.md

This file is the source of truth for every agent and every human working on this repo.

## What eco is

eco converts PDF and Markdown files to EPUB, tuned for Xteink e-readers and for general e-readers.
Milestone M1 is the core library and the `eco` CLI (`setup`, `convert`, `extract`).
A web GUI, XTC output and a Docker image follow in later milestones.

## Golden rules

- Follow ponytail, the ladder in five lines. Stop at the first rung that holds:
  1. Does this need to exist at all? If the need is speculative, skip it.
  2. Does this codebase already have it? Reuse it.
  3. Does the standard library do it? Use it.
  4. Does an installed dependency do it? Use it. Add no new one for a few lines of code.
  5. Otherwise write the smallest code that works, with one check that fails if it breaks.
- Follow antislop for UI, copy and code: plain wording, no hype, no emoji, no speculative abstractions.
  Read `DESIGN.md` before any UI work.
- No network during conversion. Only `eco setup` and the model downloader may use the network.
- Ask before any large download. Measure the size first and get a yes.
- Never commit `samples/` or book files (`*.pdf`, `*.epub`, `*.xtc`, `*.xtch`). The only exception is
  `tests/fixtures/`. CI fails on any other such file.
- Write English everywhere: code, comments, CLI text, commit messages, docs. The exceptions are
  `README.id.md` and the Indonesian documents under `docs/superpowers` and `docs/research`.

## Setup

```bash
uv sync
uv run eco setup      # downloads the AI models (about 417 MB); asks first
```

## Commands

```bash
uv run pytest                  # fast tests, no models
uv run pytest -m slow          # tests that need downloaded models
uv run pytest -m acceptance    # tests that need the local samples/ directory
uv run ruff check
uv run ruff format
```

## Architecture map

```
src/eco/__init__.py          version
src/eco/__main__.py          python -m eco
src/eco/cli.py               argparse: setup, convert, extract, web
src/eco/options.py           Options, DEVICES, ImageProfile, image_profile(), resolve_data_dir()
src/eco/events.py            Finding, StageEvent, PageEvent, FindingEvent, STAGES, Cancelled
src/eco/book.py              Block, Book
src/eco/bookfolder.py        write_book(), load_source(), BookSource, write_report()
src/eco/models.py            model setup/download/offline
src/eco/pipeline.py          extract_pdf(), convert_file(), output_path(), Result
src/eco/epub/builder.py      build_epub()
src/eco/epub/images.py       transform_image()
src/eco/epub/optimizer.py    optimize_epub(), OptimizeReport, DRMError
src/eco/epub/css.py          rewrite_css()
src/eco/epub/split.py        split_document(), anchors()
src/eco/epub/zipio.py        write_epub_zip(), check_expansion(), MAX_EPUB_BYTES
src/eco/epub/reader.py       epub_to_book()
src/eco/pdf/pages.py         PageInfo, inspect_pdf(), bookmarks(), pdf_metadata(), render_page(), crop(), to_pdfium_rect()
src/eco/pdf/docling_adapter.py  extract_blocks()
src/eco/pdf/reading_order.py fix_reading_order()
src/eco/pdf/code.py          reextract_code(), fix_code_blocks()
src/eco/pdf/regions.py       materialize_regions(), render_cover(), page_slices()
src/eco/pdf/text.py          normalize(), dehyphenate(), clean_heading_artifacts(), join_split_paragraphs(), detect_language()
src/eco/pdf/structure.py     assign_heading_levels()
src/eco/web/jobs.py          JobStore (create, reserve, adopt, rebuild), Runner, JobInfo, JobFile, safe_name(), server_lock(), RETENTION_DAYS, _work() (worker process)
src/eco/web/app.py           create_app(), _Guard (token, Host, Origin, security headers), CSP, the /api/jobs routes, _Upload (a streamed upload), Server (uvicorn that tells the app to stop)
src/eco/web/strings.py       STRINGS: every English text of the GUI
src/eco/web/templates/index.html  src/eco/web/static/app.css
tests/conftest.py  tests/fixtures/make.py  tests/**/test_*.py  tests/acceptance/{metrics.py,test_samples.py}
```

Some of these modules do not exist yet. Milestone M1 adds them task by task. The core knows nothing
about the CLI or the web. Docling and Typst are reached only through their adapters.

## How to add a fix-up pass

A fix-up pass is a pure function `(blocks, ...) -> (blocks, findings)`. It takes the list of blocks
and returns the corrected list plus the findings it wants to report. It does no I/O. Put it in
the module under `src/eco/pdf/` that fits its subject, and give it its own test file.

## Where decisions live

- The design spec: `docs/superpowers/specs/2026-11-16-epub-converter-optimizer-design.md`.
- The decision log: `docs/decisions.md`. Add a short dated entry for every new decision.

## Other agents

Claude Code reads `.claude/settings.json` and offers to install the ponytail and antislop plugins.
For other agents, install antislop with `npx antislop-ai`, or for Codex run
`codex plugin marketplace add miqdadbadjuber/anti-slop` and then `codex plugin add antislop@anti-slop`.
