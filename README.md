# eco

[Bahasa Indonesia](README.id.md)

eco converts PDF and Markdown files to EPUB and optimizes EPUB files. It tunes the result for Xteink e-readers (X4, X4 Pro, X4 v2 Classic, X3) and for general e-readers. It can reflow text, keep fixed pages, run OCR on scanned PDFs, and shrink images and file size.

eco is a command-line tool with a web GUI that runs on your own computer. It also creates XTC and XTCH files for supported Xteink devices.

## Requirements

| | macOS | Windows | Linux |
|---|---|---|---|
| System | 14+, Apple Silicon (Intel Macs are not supported) | 10/11, x64 | x64, glibc 2.28+ (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| RAM | 8 GB | 8 GB | 8 GB |
| Disk | about 3 GB | about 3 GB | about 3 GB (with the CPU build of PyTorch) |
| First download | about 0.8 GB (packages 0.35 GB, models 0.42 GB) | about 0.9 GB | about 1 GB (CPU build of PyTorch required) |
| GPU | optional (Apple GPU is used automatically) | optional | optional |

Install [uv](https://docs.astral.sh/uv/), which installs Python 3.12 for you:

```sh
# macOS or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On Windows, install the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) before `eco setup`. A clean Windows 10/11 machine can lack it, and without it PyTorch, onnxruntime and rtree cannot load, so `eco setup` and every PDF conversion fail with a DLL error.

## Install

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Then download the AI models once. The command shows the size (about 417 MB) and asks first:

```bash
eco setup
eco web
```

To upgrade, run `uv tool upgrade eco`. To remove eco, run `uv tool uninstall eco`. See the [installation check](docs/install-check.md) for an OS-specific verification checklist.

## Docker

After the first release is published, run the image with a persistent data volume and a token of at least 16 letters, digits, `_` or `-`:

```sh
docker run -d --name eco -p 8000:8000 -v eco-data:/data -e ECO_TOKEN=replace-with-a-long-secret ghcr.io/mrizkitriyanto/epub-converter-optimizer:latest
```

Open `http://<server>:8000/?token=<your-secret>`. The first visit stores the token in a browser cookie. The image runs as uid 10001; a host directory mounted at `/data` must be writable by that uid. Without models, the GUI offers to download them. For an offline server, build from this repository with `docker build --build-arg BAKE_MODELS=1 -t eco:offline .` on a connected machine, then transfer the image.

## Usage

Convert one or more files. The EPUB is named like `book.x4.epub` and is written next to the input, or into `-o DIR`:

```bash
eco convert book.pdf
eco convert book.pdf notes.md -o out/
eco convert book.pdf --device x4 --size small --mode reflow --ocr off
```

Options of `eco convert INPUT...`:

- `-o DIR`: output folder.
- `--device x4|x4-pro|x4-classic|x3|general`: target device.
- `--size small|balanced|best`: file size preset.
- `--mode auto|reflow|pages`: reflow the text or keep fixed pages.
- `--ocr auto|force|off`: OCR for scanned pages.

For XTC or XTCH, use `--style NAME` to apply a saved page style, or `--style FILE.json` for a style file. `--font NAME` and `--font-size N` override that style. `eco styles list` shows saved styles and marks the default. Without `--style`, conversions use the default style when one is set.

Add reusable `.ttf` or `.otf` fonts with `eco fonts add FILE...`; inspect them with `eco fonts list` and remove a family with `eco fonts remove FAMILY`. The data folder holds both fonts and saved styles.

Extract a PDF to an editable Markdown book folder (`book.book/`) without building an EPUB:

```bash
eco extract book.pdf -o out/
```

## Web GUI

```bash
eco web
```

This starts a local server and opens `http://127.0.0.1:8000/` in your browser. Add PDF, Markdown or EPUB files (up to 200 per upload), choose the device and the settings, and start. Progress shows the stage and the page, and you can cancel a running conversion. Review shows the findings next to the original page and a preview of the e-reader page. A click on a finding moves both. "Change settings" converts again with other settings; a PDF is not read again. Then download the EPUBs. Everything is processed on this computer. The page is in English only.

In Review, Page style controls alignment, margins, paragraph spacing, indent, and Focus Mode for XTC. Save a named style, make it the default, or delete it there. Settings on the Select files page has a Fonts section for shared font uploads and removal. A missing font uses Literata and reports a finding; missing characters in the chosen font also appear as a finding and in live preview.

Options of `eco web`:

- `--host ADDRESS`: address to listen on. The default is `127.0.0.1`, this computer only. See "Network access" below.
- `--port N`: port to listen on (default 8000).
- `--token TOKEN`: access token, at least 16 characters, each one of A-Z, a-z, 0-9, `-` or `_`. `ECO_TOKEN` does the same.
- `--max-upload-mb MB`: largest upload in MiB, for all files of one upload together, a whole number above 0 (default 500).
- `--no-browser`: do not open a browser. The address is printed as `Open: ...`.
- `--data DIR`: data folder for the models and the jobs (default: `ECO_DATA` or the app folder).

If the AI models are missing, the first page asks for them (about 417 MB: layout 172 MB, tables 213 MB, OCR 32 MB). It downloads them only after you click "Download models". "Continue without models" skips this: Markdown, EPUB and PDF files with Layout set to "Page images" convert without models.

Converted files stay in the data folder as jobs, so the page can list them as recent conversions. Jobs are deleted after 7 days (checked every hour while the server runs). To delete one sooner, with its uploads, EPUB files and previews, open it and click "Delete conversion" in Review (cancel a conversion that is still running first). One `eco web` can run per data folder; a second one stops with an error.

### Network access

An address other than `127.0.0.1`, `localhost` or `::1` needs a token. Without `--token`, eco makes one up and prints it:

```bash
eco web --host 0.0.0.0
```

It prints `Open: http://127.0.0.1:8000/?token=...`, the address for this computer, and a line saying that another device uses this computer's network address in place of `127.0.0.1` (for example `http://192.168.1.20:8000/?token=...`). A request without the token gets 401. The first request with `?token=` sets a cookie, and the page removes the token from the address bar. The connection is plain HTTP, so use it only on a network you trust. Some limits to know:

- A `?token=` link opened from another website shows 401 once, because the cookie is `SameSite=Strict`. Reload the page, or paste the link.
- The `eco_token` cookie belongs to the host, not the port. Other HTTP services on the same host receive it over plain HTTP.
- The page removes the token from the address bar, but the first address can stay in the browser's history and autocomplete, and on the command line that opened the browser.

## Privacy

Conversion never uses the network. Only `eco setup` and the "Download models" button of `eco web` download models, and only after you agree. Models load only as data formats (`.safetensors`, `.onnx`, `.npz`); pickle files are rejected. Dependencies are hash-locked and checked against a vulnerability database in CI.

## License

MIT. See [LICENSE](LICENSE). Contributors: see [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
