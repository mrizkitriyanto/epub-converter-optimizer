# Contributing

Read `AGENTS.md` first. It holds the setup, the commands and the rules for people and agents alike.

## Workflow

1. Branch from `main`.
2. Make the change with tests. Run `uv run pytest`, `uv run ruff check` and `uv run ruff format --check`.
3. Open a pull request and fill in the template.
4. Wait for CI to pass.
5. Get a review, then merge.

## Commits

Use conventional commits, in English: `feat:`, `fix:`, `docs:`, `test:`, `build:`, `refactor:`.
Keep the subject short and in the imperative mood.

## Never commit samples

Do not commit `samples/` or any `*.pdf`, `*.epub`, `*.xtc` or `*.xtch` file outside `tests/fixtures/`.
Sample books are copyrighted. CI fails if one is committed.

## Decisions

Record every new decision in `docs/decisions.md` with a date.
