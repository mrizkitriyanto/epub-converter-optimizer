# Installation verification

Run these checks on a clean machine before release. Record the date, tester, result and any failure. A pass requires `eco setup`, a PDF conversion, `eco web`, and one GUI conversion. Use a PDF you have permission to test; do not commit it.

| Platform | Date | Tester | Result | Notes |
|---|---|---|---|---|
| macOS 14+ Apple Silicon | Pending | Owner | Pending | Hardware check needed; Intel Macs are unsupported. |
| Windows 11 x64 | Pending | — | Pending | Install Microsoft Visual C++ Redistributable (x64) first. |
| Ubuntu 22.04 x64 | Pending | — | Pending | Linux needs glibc 2.28 or newer. |

For each row:

1. Install uv with the command in the README for that OS, then run `uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer`.
2. Run `eco setup` and confirm it reports models ready.
3. Run `eco convert sample.pdf` and open the resulting EPUB.
4. Run `eco web`, open the printed URL, upload the same PDF, convert it, and download the result.
5. Record the date, tester, pass or failure, and any observed error above.

The Windows local test suite and the Linux Docker smoke test are separate engineering checks; they do not substitute for these fresh-machine installation rows.
