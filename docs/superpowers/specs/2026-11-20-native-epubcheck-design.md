# Native EPUBCheck bundle

## Intent

A native eco installation should validate every EPUB it produces without requiring a system Java installation. The owner chose automatic validation and native packages for Windows, macOS, and Linux.

## Distribution

- Build one portable archive per supported platform: Windows x64, macOS arm64, Linux x64. Each archive contains the eco executable and Python dependencies, Temurin JRE 21, EPUBCheck 5.4.0, its `lib/` directory, and the upstream license notices. Users unpack the archive and run `eco` or `eco web`; there is no host Java or Python prerequisite.
- Build archives on the corresponding GitHub Actions runners. Do not commit third-party binaries. Download pinned upstream archives during the build and check their published SHA-256 values before unpacking.
- Use a one-folder PyInstaller build. The Java runtime and EPUBCheck live beside the executable under `runtime/`, outside PyInstaller's internal files. The executable resolves these relative paths, so moving the folder does not break validation.
- Keep the existing `uv tool install` path working. Native archives always validate. Source installs validate when both `ECO_JAVA` and `ECO_EPUBCHECK_JAR` are set; if neither is set, they retain the current conversion behavior. A partial configuration is an error.

## Conversion behavior

- Validate the optimized EPUB before publishing its final output path. EPUBCheck `ERROR` or `FATAL`, a nonzero process exit, or a missing bundled validator fails that file and does not leave a downloadable EPUB. Other files in a batch continue as today.
- EPUBCheck warnings are findings shown in CLI and GUI, and do not fail the output. Keep the validator's output bounded in user-facing errors. Validation runs locally, with no network access.
- XTC and XTCH output paths do not invoke EPUBCheck. When a request produces EPUB and XTC together and EPUB validation fails, fail the file before writing either output.
- Keep validation independent of the output device: general and Xteink EPUBs follow the same check.

## Approaches considered

1. Native archive per OS, selected: users need no host Python or Java, and each OS gets the correct runtime. Cost: larger downloads and three build jobs.
2. One Docker image: one Linux runtime could serve all hosts, but users would need Docker and the local desktop flow would change.
3. Download Java on first run: smaller installer, but the first conversion would depend on a network connection and the tools would not already be present at installation.

## Verification

- Unit tests cover tool discovery, warnings, errors, missing tools, and no invalid output left behind.
- The Windows bundle must run `eco --help`, start the web server, and convert a small fixture through EPUBCheck with its bundled Java. CI repeats equivalent smoke checks on macOS arm64 and Linux x64.
- The existing fast suite, Ruff checks, and EPUBCheck acceptance samples remain green.

## Known limits

- The portable archives are unsigned. macOS Gatekeeper or Windows SmartScreen may warn until signed release infrastructure exists.
- The model download remains a separate `eco setup` step; bundling the roughly 417 MB model set is outside this change.
