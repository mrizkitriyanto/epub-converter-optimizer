# Installation verification

Run these checks on a clean machine before release. Record the date, tester, result and any failure. A pass requires the native archive, `eco setup`, a PDF conversion, `eco web`, and one GUI conversion. Use a PDF you have permission to test; do not commit it.

| Platform | Date | Tester | Result | Notes |
|---|---|---|---|---|
| macOS 15+ Apple Silicon | Pending | Owner | Pending | Native package is unsigned; manual launch may need Gatekeeper approval. |
| Windows 11 x64 | Pending | Owner | Pending | Install Microsoft Visual C++ Redistributable (x64) first. |
| Ubuntu 22.04 x64 | Pending | Owner | Pending | Check glibc compatibility on the target system. |

For each row:

1. Download the matching archive from Releases, unpack it, and run `eco --help` from its `eco` folder. Do not install Java or Python on the host.
2. Run `eco setup` and confirm it reports models ready.
3. Run `eco convert sample.pdf` and open the resulting EPUB. Leave `ECO_JAVA` and `ECO_EPUBCHECK_JAR` unset so the bundled tools are exercised.
4. Run `eco web`, open the printed URL, upload the same PDF, convert it, and download the result.
5. Confirm `runtime/jre`, `runtime/epubcheck/epubcheck.jar`, `runtime/epubcheck/lib`, and both upstream license notice sets are present. Record the date, tester, pass or failure, and any observed error above.

The automated native smoke jobs and Linux Docker smoke test do not substitute for these fresh-machine checks. The older `uv tool install` flow remains available and does not need the native archive; its EPUBCheck validation requires `ECO_JAVA` and `ECO_EPUBCHECK_JAR`.
