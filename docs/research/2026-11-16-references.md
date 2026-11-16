# Referensi: PDF/Markdown → EPUB + Optimizer (umum & Xteink)

Riset 2026-11-16. Bahan untuk brainstorming dan design doc.

## 1. Device & firmware Xteink

| Device | Layar (portrait) | Chip | Catatan |
|---|---|---|---|
| X4 | 480×800, 4.3", ~220 PPI | ESP32-C3, ~380 KB RAM usable | e-ink 4 level abu-abu (SSD1677) |
| X3 | 528×792, 3.7" | ESP32-C3 | sama controller |
| X4 Pro | 480×800, touchscreen, front light | ESP32-S3 (+PSRAM) | firmware pihak ketiga diizinkan |

- **Firmware bawaan**: EPUB, TXT, XTC/XTCH. **Tidak menampilkan gambar di dalam EPUB sama sekali** (diuji epubkit di X3 & X4).
- **CrossPoint Reader** (`crosspoint-reader/crosspoint-reader`, ★8.8k, C++): firmware komunitas utama. EPUB 2/3, gambar, hyphenation, tabel, footnote, custom font (`.cpfont`, atau TTF bila ada external RAM), cache per-chapter ke SD. Web UI file transfer **sudah punya "EPUB Optimizer"**.
- **Fork**: CrossInk (`uxjulia/CrossInk`, ★1.9k, MIT) — stable page numbers via `META-INF/x-locations.json`; saran resmi: EPUB text-first, idealnya < 20 MB. Papyrix (`bigbag/papyrix-reader`, ★515, MIT) — **Markdown & FB2 native**, dokumentasi batas gambar paling detail. Witch(hunt) Reader — Markdown native.

### Batas teknis yang harus dipenuhi profil Xteink

Sumber: docs Papyrix (`docs/images.md`), README CrossPoint/CrossInk, epubkit.

- JPEG **baseline** (SOF0/SOF1) saja di X4 original & X3. Progressive → placeholder (X4 Pro bisa, maks 512 KiB). Arithmetic-coded JPEG ditolak semua device.
- PNG didukung (transparansi jadi opaque), BMP didukung. **GIF, SVG, WebP, TIFF tidak didukung.**
- Gambar < 20 px di-skip; gambar `data:` URI di-skip; batas decode 2048×3072.
- Font embedded memperlambat/menghabiskan memori → buang (device punya font sendiri).
- Chapter sangat besar / ribuan section → lambat atau gagal → pecah chapter besar.
- CSS float/flex/grid/position fixed bermasalah → hapus.

## 2. Tool sejenis (optimizer EPUB & XTC)

| Tool | Isi | Lisensi / stack |
|---|---|---|
| `bigbag/epub-to-xtc-converter` (ref) | Web + Node CLI. EPUB→XTC/XTCH via CREngine WASM; optimizer: hapus CSS bermasalah, strip font, gambar grayscale + resize + baseline JPEG, hapus SVG/WebP/TIFF, inject CSS e-paper, stable pages CrossInk | MIT, JS, sharp, JSZip |
| `b1rdmania/epubkit` (ref) | Web, Python di browser (Pyodide). Pipeline 20 langkah: DRM check, gambar 4-level + Floyd-Steinberg, unwrap SVG cover, generate cover, repair XHTML (lxml), hapus CSS tak terpakai, strip font, text cleanup (ligature OCR, mojibake), fix/generate TOC, bersihkan metadata toko & file OS, template nama file | MIT, Pillow, lxml, cssutils |
| `chazeon/xtctool` | **PDF / Markdown / Typst / gambar → XTC/XTCH** (pre-render, supersampling + dithering) | GPL-3, Python |
| x4converter.rho.sh | Web converter EPUB→XTC pertama (CREngine WASM) | inspirasi bigbag |
| cr2xt | Desktop converter EPUB→XTC (CoolReader) | — |
| `llbxg/toxtc`, `cbz2xtc` (PyPI) | Toolkit Python XTC; komik CBZ→XTC | — |
| Gist CrazyCoder | Spesifikasi format XTC/XTCH/XTG/XTH | — |
| `zgredex/baseline_jpg_converter`, `kxrz/calibre_workflow` | Plugin Calibre: baseline JPEG; repair HTML/CSS | — |
| `pgaskin/kepubify` | EPUB→KEPUB (Kobo), single binary Go, cepat — contoh CLI yang rapi | MIT |
| KCC (`ciromattia/kcc`) | Optimizer komik/manga untuk e-ink (Kindle/Kobo); referensi pemrosesan gambar | — |

## 3. PDF → teks terstruktur (bagian tersulit)

| Tool | Kekuatan | Kelemahan / lisensi |
|---|---|---|
| Docling (★70k) | Layout, tabel, reading order, OCR; output Markdown/HTML/JSON | MIT; berat (PyTorch + model) |
| Marker (★41k) | Akurasi tinggi. Mode `no_ocr` (CPU, ~57 hal/detik, bagus untuk PDF digital), `fast` (CPU), `balanced` (GPU) | Kode Apache-2.0; bobot model OpenRAIL-M (gratis personal/riset/startup < $5M) |
| OpenDataLoader PDF (★30k) | Parser PDF, fokus aksesibilitas | Apache-2.0, Java |
| PyMuPDF4LLM | Cepat, tanpa ML, PDF→Markdown | **AGPL-3.0** |
| pdfplumber | Ekstraksi char/garis detail | MIT; tanpa pemahaman layout |
| pdf.js | Ekstraksi teks di browser (client-side) | Apache-2.0; heuristik layout harus dibuat sendiri |
| Calibre `ebook-convert` | PDF→EPUB paling matang tanpa ML | GPL-3; dependency besar |
| k2pdfopt / ReflowPDF (WASM) | Reflow PDF jadi potongan gambar untuk layar kecil (multi-kolom, scan) | output tetap PDF/gambar, bukan teks |
| OCRmyPDF | Tambah layer teks OCR ke PDF scan (Tesseract) | MPL-2.0 |
| `pdf-to-epub` (PyPI 0.1.0) | Docling → HTML → EPUB 3 | MIT; masih awal |

Jenis PDF menentukan pendekatan:
1. **PDF digital, layout sederhana** (novel, artikel): ekstraksi teks + heuristik cukup.
2. **PDF digital, layout kompleks** (multi-kolom, tabel, rumus, catatan kaki): butuh model layout (Docling/Marker).
3. **PDF scan**: butuh OCR (Marker/Docling/OCRmyPDF).

## 4. Markdown → EPUB

- **Pandoc** (★47k, GPL-2): standar de facto. Metadata YAML, TOC, footnote, math (MathML), syntax highlight. Dipanggil sebagai binary eksternal, jadi lisensi tool kita tetap bebas.
- Python: `markdown-it-py` (MIT) + packager EPUB sendiri (OPF + `nav.xhtml` + zip). `ebooklib` praktis tapi **AGPL-3**.
- Browser/JS: `markdown-it`/`marked` (MIT) + JSZip + packager sendiri; `epub-gen-memory` (MIT) tidak aktif sejak 2024.
- Untuk Xteink: rumus MathML dan SVG tidak dirender → perlu dirender jadi PNG/JPEG; blok kode lebar perlu wrap.

## 5. Kompresi & validasi

- **Gambar = penghematan terbesar**: resize ke layar target, grayscale, JPEG baseline kualitas ~75–85 (mozjpeg), PNG palette kecil untuk line art. Dedupe gambar identik.
- **Font**: buang (Xteink) atau subset (umum) via fontTools `pyftsubset` (MIT). Calibre `ebook-polish` melakukan subset font, kompres gambar lossless, hapus CSS tak terpakai.
- **ZIP**: deflate level 9; Zopfli (Apache-2.0) atau `advzip` biasanya hanya menambah beberapa persen, tetap kompatibel. Entry `mimetype` **wajib pertama dan STORED** (tanpa kompresi).
- **Bersihkan**: file OS (`.DS_Store`, `__MACOSX`), item manifest tak terpakai, metadata toko, minify CSS/XHTML (kecuali `<pre>`).
- **Validasi**: EPUBCheck (W3C, BSD-3, Java).

## Sumber

- Repo (dibaca via GitHub API): `bigbag/epub-to-xtc-converter`, `b1rdmania/epubkit`, `crosspoint-reader/crosspoint-reader`, `uxjulia/CrossInk`, `bigbag/papyrix-reader` (+ `docs/images.md`), `chazeon/xtctool`, `llbxg/toxtc`, `datalab-to/marker`, `docling-project/docling`, `pymupdf/pymupdf4llm`, `aerkalov/ebooklib`, `jgm/pandoc`, `kovidgoyal/calibre`, `w3c/epubcheck`, `pgaskin/kepubify`, `ocrmypdf/OCRmyPDF`, `mozilla/pdf.js`, `cpiber/epub-gen-memory`, `jsvine/pdfplumber`, `google/zopfli`, `fonttools/fonttools`, `opendataloader-project/opendataloader-pdf`
- [Digital Trends: Xteink X4 review](https://www.digitaltrends.com/phones/xteink-x4-review/)
- [Xteink X4 Pro FAQ](https://www.xteink.com/blogs/product/x4-pro-faq-specs-support)
- [LWN: A look at CrossPoint e-reader firmware](https://lwn.net/Articles/1087635/)
- [Liliputing: CrossPoint Reader](https://liliputing.com/crosspoint-reader-is-an-open-source-replacement-for-xteink-x4-ereaders-default-firmware)
- [CrazyCoder: XTC format spec (gist)](https://gist.github.com/CrazyCoder/b125f26d6987c0620058249f59f1327d)
- [cbz2xtc (PyPI)](https://pypi.org/project/cbz2xtc/)
- [cr2xt desktop XTC converter](https://www.readme.club/resources/cr2xt-desktop-xtc-converter-b2c83171)
- [Best open-source PDF-to-Markdown tools 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [DAISY: PDF Conversions Put to the Test](https://daisy.org/activities/projects/ai-special-interest-group/pdf-conversions-put-to-the-test/)
- [pdf-to-epub 0.1.0 (PyPI)](https://pypi.org/project/pdf-to-epub/0.1.0/)
- [k2pdfopt](https://willus.com/k2pdfopt/) · [ReflowPDF](https://www.producthunt.com/products/reflowpdf)
- [calibre ebook-polish man page](https://man.archlinux.org/man/ebook-polish.1.en)
- [Kindle Comic Converter](https://github.com/ciromattia/kcc)
