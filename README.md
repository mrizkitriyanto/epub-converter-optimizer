# eco

[Bahasa Indonesia](README.id.md)

eco converts PDF and Markdown files to EPUB. It tunes the result for Xteink e-readers (X4, X4 Pro, X4 v2 Classic, X3) and for general e-readers. It can reflow text, keep fixed pages, run OCR on scanned PDFs, and shrink images and file size.

eco is a command-line tool with a web GUI that runs on your own computer. XTC output is planned.

## Requirements

| | macOS | Windows | Linux |
|---|---|---|---|
| System | 14+, Apple Silicon (Intel Macs are not supported) | 10/11, x64 | x64, glibc 2.28+ (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| RAM | 8 GB | 8 GB | 8 GB |
| Disk | about 3 GB | about 3 GB | about 3 GB (with the CPU build of PyTorch) |
| First download | about 0.8 GB (packages 0.35 GB, models 0.42 GB) | about 0.9 GB | about 1 GB (CPU build of PyTorch required) |
| GPU | optional (Apple GPU is used automatically) | optional | optional |

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you.

On Windows, install the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) before `eco setup`. A clean Windows 10/11 machine can lack it, and without it PyTorch, onnxruntime and rtree cannot load, so `eco setup` and every PDF conversion fail with a DLL error.

## Install

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Then download the AI models once. The command shows the size (about 417 MB) and asks first:

```bash
eco setup
```

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

Extract a PDF to an editable Markdown book folder (`book.book/`) without building an EPUB:

```bash
eco extract book.pdf -o out/
```

## Web GUI

```bash
eco web
```

This starts a local server and opens `http://127.0.0.1:8000/` in your browser. Add PDF, Markdown or EPUB files (up to 200 per upload), choose the device and the settings, and start. Progress shows the stage and the page, and you can cancel a running conversion. Review shows the findings next to the original page and a preview of the e-reader page. A click on a finding moves both. "Change settings" converts again with other settings; a PDF is not read again. Then download the EPUBs. Everything is processed on this computer.

Options of `eco web`:

- `--host ADDRESS`: address to listen on. The default is `127.0.0.1`, this computer only. See "Network access" below.
- `--port N`: port to listen on (default 8000).
- `--token TOKEN`: access token, at least 16 characters, each one of A-Z, a-z, 0-9, `-` or `_`. `ECO_TOKEN` does the same.
- `--max-upload-mb MB`: largest upload in MiB, for all files of one upload together (default 500).
- `--no-browser`: do not open a browser. The address is printed as `Open: ...`.
- `--data DIR`: data folder for the models and the jobs (default: `ECO_DATA` or the app folder).

If the AI models are missing, the first page asks for them (about 417 MB: layout 172 MB, tables 213 MB, OCR 32 MB). It downloads them only after you click "Download models". "Continue without models" skips this: Markdown, EPUB and PDF files with Layout set to "Page images" convert without models.

Converted files stay in the data folder as jobs, so the page can list them as recent conversions. Jobs are deleted after 7 days (checked every hour while the server runs). One `eco web` can run per data folder; a second one stops with an error.

### Network access

An address other than `127.0.0.1`, `localhost` or `::1` needs a token. Without `--token`, eco makes one up and prints it:

```bash
eco web --host 0.0.0.0
```

The printed address is `http://0.0.0.0:8000/?token=...`. On another device, use this computer's address instead of `0.0.0.0`. A request without the token gets 401. The first request with `?token=` sets a cookie, and the page removes the token from the address bar. The connection is plain HTTP, so use it only on a network you trust. Some limits to know:

- A `?token=` link opened from another website shows 401 once, because the cookie is `SameSite=Strict`. Reload the page, or paste the link.
- The `eco_token` cookie belongs to the host, not the port. Other HTTP services on the same host receive it over plain HTTP.
- The page removes the token from the address bar, but the first address can stay in the browser's history and autocomplete, and on the command line that opened the browser.

## Privacy

Conversion never uses the network. Only `eco setup` and the "Download models" button of `eco web` download models, and only after you agree. Models load only as data formats (`.safetensors`, `.onnx`, `.npz`); pickle files are rejected. Dependencies are hash-locked and checked against a vulnerability database in CI.

## License

MIT. See [LICENSE](LICENSE). Contributors: see [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
