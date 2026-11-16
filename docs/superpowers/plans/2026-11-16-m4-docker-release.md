# M4: Docker + Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `eco` deployable as one Docker image (GHCR, amd64 + arm64) and releasable by pushing a version tag, with install docs verified on macOS, Windows and Linux.

**Architecture:**
- The image is built from `python:3.12-slim-bookworm` with uv: CPU torch from the lockfile, a non-root user, a `/data` volume, and `eco web` on `0.0.0.0:8000`. The token is required in that mode (M2 behavior).
- Models are downloaded on first start through the GUI setup gate. An optional build arg bakes them into the image for offline servers.
- A tag `vX.Y.Z` runs a workflow that checks the version, builds and pushes multi-arch images, and creates a GitHub release.

**Tech Stack:** Docker, GitHub Actions (`docker/setup-qemu-action@v4`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/metadata-action@v6`, `docker/build-push-action@v7`), `gh` CLI, uv `0.13.6`.

**Spec:** `docs/superpowers/specs/2026-11-16-epub-converter-optimizer-design.md` §8.15, §6.2, §9 item 11. Prerequisite: M3 merged.

## Global Constraints

- Everything in M1–M3's Global Constraints still applies.
- Image: base `python:3.12-slim-bookworm`; `COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/`; install with `uv sync --locked --no-dev` (Linux resolves CPU torch from the lock).
- Runtime user uid `10001`; `ECO_DATA=/data`; `VOLUME /data`; `EXPOSE 8000`; default command `eco web --host 0.0.0.0 --port 8000 --no-browser`; token from env `ECO_TOKEN` (auto-generated and printed if absent).
- Optional `--build-arg BAKE_MODELS=1` stores the models in `/opt/eco-models` and sets `ECO_MODELS=/opt/eco-models`.
- Image name `ghcr.io/mrizkitriyanto/epub-converter-optimizer`, with tags `X.Y.Z` and `latest`; platforms `linux/amd64,linux/arm64`.
- The release tag must equal `v` + `eco.__version__`.
- No secrets in the image or the logs, except the auto-generated token, which is printed once on purpose.

## Review Focus

1. Container started on `0.0.0.0` without `ECO_TOKEN` → the token is printed in the logs and requests without it get 401 (Task 3 smoke test).
2. Host-mounted `/data` that is not writable by uid 10001 → `eco web` exits with `error: Data directory not writable: /data` instead of a traceback (Task 1 test).
3. Fresh container without models → the GUI shows the setup gate. `/api/health` still reports ok (Task 1 and Task 3).
4. Apple Silicon and other arm64 hosts → the image runs natively, because it is built for `linux/arm64` too (Task 3).
5. Upgrading the image with an existing `/data` → old jobs still list. A models marker from another Docling version makes the setup gate ask to re-download instead of crashing (Task 1 test).

---

## File Structure

```
Dockerfile  .dockerignore
.github/workflows/ci.yml        (modify: docker job)
.github/workflows/release.yml
src/eco/models.py               (modify: ECO_MODELS, version-aware marker)
src/eco/web/app.py              (modify: /api/health, writable data check)
src/eco/cli.py                  (modify: data dir check message)
scripts/docker-smoke.sh
docs/install-check.md
README.md  README.id.md  CONTRIBUTING.md (modify)
tests/test_deploy_bits.py
```

---

### Task 1: Health, models location, data-dir checks

**Files:**
- Modify: `src/eco/models.py`, `src/eco/web/app.py`, `src/eco/cli.py`
- Create: `tests/test_deploy_bits.py`

**Interfaces:**
- Produces:
  - `GET /api/health` (exempt from the token) → `{"ok": true, "version": "<eco.__version__>", "models_ready": bool}`.
  - `models_dir(data_dir)` returns `Path(os.environ["ECO_MODELS"])` when that variable is set.
  - `models_ready(d)` is true only when `.complete` contains the current `docling.__version__`.
  - `eco web` and `eco convert` check up front that the data directory is writable, and otherwise exit 1 with `error: Data directory not writable: <path>`.

- [ ] **Step 1: Write failing tests**

```python
def test_health_without_token(tmp_path):
    r = TestClient(create_app(tmp_path, token="t")).get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True

def test_models_env_and_version_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("ECO_MODELS", str(tmp_path / "m"))
    d = models_dir(tmp_path / "data"); d.mkdir(parents=True)
    (d / ".complete").write_text("0.0.1")
    assert d == tmp_path / "m" and not models_ready(d)

def test_unwritable_data_dir(tmp_path, capsys):
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(0o500)
    assert main(["convert", "x.md", "--data", str(ro)]) == 1
    assert "Data directory not writable" in capsys.readouterr().err
```

  (Skip the last test on Windows and when running as root.)
- [ ] **Steps 2–4:** FAIL → implement → PASS. **Step 5: Commit**: `git commit -m "feat: health endpoint, ECO_MODELS, data dir checks"`

### Task 2: Dockerfile and smoke script

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `scripts/docker-smoke.sh`

**Interfaces:**
- Produces: an image that serves the GUI on port 8000; `scripts/docker-smoke.sh IMAGE` exits 0 when all checks pass.
- Dockerfile (in order):
  1. `FROM python:3.12-slim-bookworm`
  2. `apt-get install --no-install-recommends libglib2.0-0 libgomp1`, then clean the apt lists.
  3. Copy uv 0.13.6.
  4. Set `UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never`.
  5. `WORKDIR /app`.
  6. Copy `pyproject.toml uv.lock README.md` and run `uv sync --locked --no-dev --no-install-project` (layer cache).
  7. Copy `src`, then run `uv sync --locked --no-dev`.
  8. `ARG BAKE_MODELS=0`; if `1`, run `ECO_MODELS=/opt/eco-models /app/.venv/bin/eco setup --yes`, and set `ENV ECO_MODELS=/opt/eco-models` via an `ARG`-derived env.
  9. `useradd --uid 10001 --create-home eco`; `mkdir /data && chown eco /data`.
  10. `USER eco`.
  11. `ENV PATH=/app/.venv/bin:$PATH ECO_DATA=/data`; `VOLUME /data`; `EXPOSE 8000`.
  12. `HEALTHCHECK` using `python -c` and `urllib` on `/api/health`.
  13. `CMD ["eco","web","--host","0.0.0.0","--port","8000","--no-browser"]`.
- `.dockerignore`: `samples/ out/ .venv/ .git/ .superpowers/ tests/ docs/ **/__pycache__`.
- `docker-smoke.sh IMAGE`:
  1. run with `-e ECO_TOKEN=smoke` and wait ≤ 60 s for `/api/health` = 200;
  2. `GET /` without the token → 401; with `Authorization: Bearer smoke` → 200;
  3. `docker exec` `printf '# A\n\nText.\n' > /data/a.md && eco convert /data/a.md --data /data` → `/data/a.x4.epub` exists. Markdown needs no models;
  4. run a second container without `ECO_TOKEN` and check that its logs contain `?token=`.

- [ ] **Step 1: Build and run the smoke test locally**:
  - `docker build -t eco:dev . && bash scripts/docker-smoke.sh eco:dev` → exit 0;
  - `docker image ls eco:dev` size is recorded in `docs/decisions.md` (expected roughly 2–3 GB with CPU torch).
- [ ] **Step 2: Commit**: `git commit -m "build: Docker image with non-root user, /data volume, smoke test"`

### Task 3: CI docker job and release workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`

**Interfaces:**
- `ci.yml` job `docker` (ubuntu, on pull requests and main): `docker build -t eco:ci .`, then `bash scripts/docker-smoke.sh eco:ci`.
- `release.yml`:
  - Runs on `push: tags: ['v*']`, with `permissions: contents: write, packages: write`.
  - Steps:
    1. `actions/checkout@v7`.
    2. Version check: `test "$GITHUB_REF_NAME" = "v$(sed -n 's/^__version__ = \"\\(.*\\)\"/\\1/p' src/eco/__init__.py)"`.
    3. setup-qemu@v4, setup-buildx@v4.
    4. login-action@v4 to `ghcr.io` with `${{ github.actor }}` / `${{ secrets.GITHUB_TOKEN }}`.
    5. metadata-action@v6 (tags `type=semver,pattern={{version}}` and `type=raw,value=latest`).
    6. build-push-action@v7 with `platforms: linux/amd64,linux/arm64`, `push: true`.
    7. `gh release create "$GITHUB_REF_NAME" --generate-notes` with `GH_TOKEN: ${{ github.token }}`.

- [ ] **Step 1: Validate the workflows** with `uvx actionlint` (or `docker run --rm -v $PWD:/repo rhysd/actionlint:latest -color` from the repo root) → no errors.
- [ ] **Step 2: Dry-run the release** on a fork or test tag, only with the owner's permission, since it publishes an image: push `v0.0.0-test` with a matching temporary `__version__` and confirm the image appears in GHCR for both platforms; then delete the test tag, release and package versions.
- [ ] **Step 3: Commit**: `git commit -m "ci: docker smoke job and tag-driven multi-arch release"`

### Task 4: Install and deploy docs, per-OS verification

**Files:**
- Modify: `README.md`, `README.id.md`, `CONTRIBUTING.md`
- Create: `docs/install-check.md`

- [ ] **Step 1: Write the install sections** (identical content in both languages):
  - **Install uv:**
    - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
    - Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - **Install and run:** `uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer`, then `eco setup`, then `eco web`.
  - **Upgrade:** `uv tool upgrade eco`.
  - **Uninstall:** `uv tool uninstall eco`.
  - **Docker:** `docker run -d --name eco -p 8000:8000 -v eco-data:/data -e ECO_TOKEN=<your-secret> ghcr.io/mrizkitriyanto/epub-converter-optimizer:latest`, then open `http://<server>:8000/?token=<your-secret>`.
  - **Offline servers:** build with `--build-arg BAKE_MODELS=1`.
  - **Requirements table** from spec §6.2, including "Intel Macs are not supported".
- [ ] **Step 2: Write `docs/install-check.md`**: a per-OS table (macOS 14+ Apple Silicon, Windows 11 x64, Ubuntu 22.04 x64) with the steps install → `eco setup` → `eco convert` on a sample PDF → `eco web` → one GUI conversion. It has columns for date, tester, result and notes (spec §9 item 11).
- [ ] **Step 3: Add "Releasing" to `CONTRIBUTING.md`**: bump `__version__`, commit, `git tag vX.Y.Z`, `git push --tags`; the workflow publishes the image and the release.
- [ ] **Step 4: Run the macOS row** of `docs/install-check.md` on the owner's Mac and record the result. The Windows and Linux rows are filled by whoever has those machines.
- [ ] **Step 5: Commit**: `git commit -m "docs: install, Docker deploy, release process, per-OS checks"`
