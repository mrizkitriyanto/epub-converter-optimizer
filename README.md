# eco

[Bahasa Indonesia](README.id.md)

eco converts PDF and Markdown files to EPUB and optimizes EPUB files. It tunes the result for Xteink e-readers (X4, X4 Pro, X4 v2 Classic, X3) and for general e-readers. It can reflow text, keep fixed pages, run OCR on scanned PDFs, and shrink images and file size.

eco is a command-line tool with a web GUI that runs on your own computer. It also creates XTC and XTCH files for supported Xteink devices.

## Requirements

| | Windows | macOS | Linux |
|---|---|---|---|
| Native package | Windows 10/11 x64 | macOS 15+ Apple Silicon | Ubuntu 22.04 x64 or a compatible distribution |
| Source install | Windows 10/11 x64 | macOS 14+ Apple Silicon | x64, glibc 2.28+ |
| Memory | 8 GB recommended | 8 GB recommended | 8 GB recommended |
| Free disk space | About 3 GB, plus room for input and output files | About 3 GB, plus room for input and output files | About 3 GB, plus room for input and output files |

Each native archive includes eco, Python, a private Temurin Java runtime, and EPUBCheck. You do not need a system Python or Java installation. Windows still needs the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) for PyTorch and other native libraries. Native archives are built and smoke tested on their matching OS; compatibility with older releases is not established.

PDF reflow, tables, and OCR need an additional one-time model download of about 417 MB. Markdown, EPUB input, and PDF page images can work before that download. Conversion itself uses no network.

## Install the native app

Choose `eco-<version>-windows-x64.zip`, `eco-<version>-macos-arm64.tar.gz`, or `eco-<version>-linux-x64.tar.gz` from [Releases](https://github.com/mrizkitriyanto/epub-converter-optimizer/releases). Before the first tagged native release, download `eco-native-<OS>` under **Artifacts** on the [successful three-OS build](https://github.com/mrizkitriyanto/epub-converter-optimizer/actions/runs/44693577065); that download is a ZIP containing the platform archive, and GitHub artifacts expire. Keep the extracted `eco` folder intact: its `runtime/` and `_internal/` folders are required.

### Windows

Extract the ZIP, open PowerShell in the extracted `eco` folder, then run:

```powershell
.\eco.exe --help
.\eco.exe web
```

The web app opens at `http://127.0.0.1:8000/`. It will offer the model download if needed. For CLI PDF conversion, run `.\eco.exe setup` first; it shows the download size and asks before downloading. To try the app without models, upload a Markdown file in the web app.

### macOS and Linux

Extract the TAR.GZ archive, open a terminal in the extracted `eco` folder, then run `./eco --help` and `./eco web`. For CLI PDF conversion, run `./eco setup` first. The macOS archive is unsigned, so macOS may require you to approve its first launch.

Every EPUB produced by a native package is checked with its bundled EPUBCheck before the file is published. An EPUBCheck error fails that conversion; warnings appear in the findings. `runtime/jre/bin/java` and `runtime/epubcheck/epubcheck.jar` belong to eco and do not need to be installed separately.

To update, extract the newer archive to a new folder. Your models, fonts, saved styles, and web jobs live in the user data folder unless you chose `--data` or `ECO_DATA`, so replacing the application folder does not replace that data.

## Install from source with uv

Install [uv](https://docs.astral.sh/uv/), which installs Python 3.12 for you:

```sh
# macOS or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Then download the AI models once. The command shows the size (about 417 MB) and asks first:

```bash
eco setup
eco web
```

Source installs validate EPUBs when both `ECO_JAVA` and `ECO_EPUBCHECK_JAR` point to a Java executable and an EPUBCheck JAR. Without them, conversion still works but skips EPUBCheck. A partial configuration fails clearly. To upgrade, run `uv tool upgrade eco`; to remove it, run `uv tool uninstall eco`. See the [installation check](docs/install-check.md) for an OS-specific verification checklist.

## Docker

After the first release is published, run the image with a persistent data volume and a token of at least 16 letters, digits, `_` or `-`:

```sh
docker run -d --name eco -p 8000:8000 -v eco-data:/data -e ECO_TOKEN=replace-with-a-long-secret ghcr.io/mrizkitriyanto/epub-converter-optimizer:latest
```

Open `http://<server>:8000/?token=<your-secret>`. The first visit stores the token in a browser cookie. The image runs as uid 10001; a host directory mounted at `/data` must be writable by that uid. Without models, the GUI offers to download them. For an offline server, build from this repository with `docker build --build-arg BAKE_MODELS=1 -t eco:offline .` on a connected machine, then transfer the image.

## Usage

The examples below use `eco`. In a native archive, run `./eco` on macOS/Linux or `.\eco.exe` in PowerShell instead. Convert one or more PDF, Markdown, or EPUB files, or name a folder to convert its supported files. The EPUB is named like `book.x4.epub` and is written next to the input, or into `-o DIR`:

```bash
eco convert book.pdf
eco convert book.pdf notes.md -o out/
eco convert book.pdf --device x4 --size small --mode reflow --ocr off
eco convert book.pdf --device x4 --format epub,xtc --firmware crosspoint
eco convert existing.epub --device general -o out/
```

Options of `eco convert INPUT...`:

- `-o DIR`: output folder.
- `--device x4|x4-pro|x4-classic|x3|general`: target device.
- `--size small|balanced|best`: file size preset.
- `--mode auto|reflow|pages`: reflow the text or keep fixed pages.
- `--ocr auto|force|off`: OCR for scanned pages.
- `--format epub|xtch|xtc`: output format; use a comma-separated list such as `epub,xtc` for more than one. XTC and XTCH need a supported Xteink device.
- `--firmware any|stock|crosspoint|crossink`: firmware profile for Xteink output.
- `--landscape`: turn Xteink pages sideways.
- `--title`, `--author`, `--lang`: override book metadata; `--lang` accepts a code such as `en` or `id`.
- `--data DIR`: data folder; `ECO_DATA` also selects it. By default, eco uses your user data folder.
- `--focus-mode`: bold the start of words in the EPUB's XHTML so it opens with Focus Mode on the reader. Also applies to XTC output. Words of up to 3 letters get 1 bold letter, 4-letter words 2, longer words 40% (rounded). Use `--focus-weight 600|700` for semibold or bold (default: 700).

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

This starts a local server and opens `http://127.0.0.1:8000/` in your browser. The page has four steps: Select, Convert, Review and Export. Everything is processed on this computer. The page is in English only.

- **Select:** add PDF, Markdown or EPUB files (up to 200 per upload). Each PDF shows its page count, whether it is digital or scanned, a time estimate, and a map with one square per page that marks the scanned pages. Choose the reading device, EPUB or XTC output, a saved reading style and the file size, then start. Firmware, OCR, layout, title, author, language and the Fonts library are under **More settings**. When the AI models are missing, a notice offers to download them; Markdown, EPUB and PDFs made into page images convert without them.
- **Convert:** the percent, the time left and the time so far, one segment per stage, and for a PDF a page map that fills as pages are read. Warnings appear as they are found. You can cancel a running conversion. Review opens by itself when the first file is done.
- **Review:** the findings next to the original page and a preview of the e-reader page; a click on a finding moves both. The strip above them has one bar per page and marks the pages with a warning; click it or use the arrow keys to move through the book. Text size, line spacing, side margins, first-line indent and Focus Mode change the preview at once and say "changed" until you select **Apply to book**, which rebuilds the files with the new style (a PDF is not read again) and returns to the same page. **Advanced typography** holds every style value, including alignment and paragraph spacing, and lets you save a named style, make it the default, or delete it. A missing font uses Literata and reports a finding; missing characters in the chosen font also appear as a finding and in the live preview. Each converted file needs review before Export.
- **Export:** a download button for each file, the EPUBCheck result, and the style that was applied.

Focus Mode bolds the start of Latin, Greek, and Cyrillic words in the EPUB text itself, including when the input is an EPUB, so no e-reader setting or script is needed. Code and math are left alone. The e-reader may still override book formatting.

Options of `eco web`:

- `--host ADDRESS`: address to listen on. The default is `127.0.0.1`, this computer only. See "Network access" below.
- `--port N`: port to listen on (default 8000).
- `--token TOKEN`: access token, at least 16 characters, each one of A-Z, a-z, 0-9, `-` or `_`. `ECO_TOKEN` does the same.
- `--max-upload-mb MB`: largest upload in MiB, for all files of one upload together, a whole number above 0 (default 500).
- `--no-browser`: do not open a browser. The address is printed as `Open: ...`.
- `--data DIR`: data folder for the models and jobs (default: `ECO_DATA` or your user data folder).

If the AI models are missing, the first page asks for them (about 417 MB: layout 172 MB, tables 213 MB, OCR 32 MB). It downloads them only after you click "Download models". "Continue without models" skips this: Markdown, EPUB and PDF files with Layout set to "Page images" convert without models.

Converted files stay in the data folder as jobs, so the page can list them as recent conversions. Jobs are deleted after 7 days (checked every hour while the server runs). To delete one sooner, with its uploads, EPUB files and previews, open it and click "Delete this conversion" on Export, or on Convert after a conversion failed (cancel a conversion that is still running first). One `eco web` can run per data folder; a second one stops with an error.

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

## Troubleshooting

- **PDF asks for models:** run `eco setup` or use the GUI's **Download models** button. Markdown and EPUB input work without models. PDF page images are available through the GUI without them.
- **Windows reports a missing DLL:** install the x64 Visual C++ Redistributable linked under [Requirements](#requirements), then reopen eco.
- **EPUBCheck or Java is missing:** extract the whole native archive again. The executable needs its sibling `runtime/` folder; moving only `eco.exe` or `eco` breaks validation.
- **Port 8000 is in use:** start the GUI with `eco web --port 8765` and open `http://127.0.0.1:8765/`.
- **A native conversion fails EPUBCheck:** the invalid EPUB is not published. Review the error or warning shown by eco and try a different conversion mode or report the input and message in an issue. Source installs only run EPUBCheck when both `ECO_JAVA` and `ECO_EPUBCHECK_JAR` are set.

For a full installation check, including a PDF and a GUI conversion on each OS, follow [docs/install-check.md](docs/install-check.md).

## License

MIT. See [LICENSE](LICENSE). Contributors: see [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
