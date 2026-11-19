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

## Releasing

Update `src/eco/__init__.py` and `pyproject.toml` to the same version, refresh `uv.lock`, run the checks in [docs/install-check.md](docs/install-check.md), and commit. After the release commit is merged to `main`, tag it `vX.Y.Z` and push the tag. The release workflow checks the tag against `eco.__version__`, builds amd64 and arm64 images, publishes them to GHCR, and creates a GitHub release. Tagging and pushing require the owner's approval.
