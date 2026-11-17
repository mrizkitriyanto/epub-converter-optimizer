# eco

[Bahasa Indonesia](README.id.md)

eco converts PDF and Markdown files to EPUB. It tunes the result for Xteink e-readers (X4, X4 Pro, X4 v2 Classic, X3) and for general e-readers. It can reflow text, keep fixed pages, run OCR on scanned PDFs, and shrink images and file size.

Today it is a command-line tool. A web GUI and XTC output are planned.

## Requirements

| | macOS | Windows | Linux |
|---|---|---|---|
| System | 14+, Apple Silicon (Intel Macs are not supported) | 10/11, x64 | x64, glibc 2.28+ (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| RAM | 8 GB | 8 GB | 8 GB |
| Disk | about 3 GB | about 3 GB | about 3 GB (with the CPU build of PyTorch) |
| First download | about 0.9 GB (packages 0.35 GB, models 0.57 GB) | about 1 GB | about 1.1 GB (CPU build of PyTorch required) |
| GPU | optional (Apple GPU is used automatically) | optional | optional |

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you.

## Install

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Then download the AI models once. The command shows the size (about 568 MB) and asks first:

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

## Privacy

Conversion never uses the network. Only `eco setup` downloads models, and only after it asks. Models load only as data formats (`.safetensors`, `.onnx`, `.npz`); pickle files are rejected. Dependencies are hash-locked and checked against a vulnerability database in CI.

## License

MIT. See [LICENSE](LICENSE). Contributors: see [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
