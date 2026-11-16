# Desain: eco (epub-converter-optimizer)

- Tanggal: 2026-11-16
- Status: draft, menunggu persetujuan pemilik
- Bahan pendukung: [referensi](../../research/2026-11-16-references.md), [hasil spike mesin PDF](../../research/2026-11-16-spike-pdf-engines.md)

## 1. Ringkasan

`eco` adalah aplikasi lokal untuk macOS, Windows, dan Linux, dengan **CLI** dan **GUI web**. Aplikasi ini mengubah PDF (digital, multi-kolom, atau hasil scan) dan Markdown menjadi EPUB yang dioptimalkan dan dikompres untuk e-reader umum atau Xteink. Hasilnya juga bisa dirender ke XTC/XTCH, format halaman jadi milik Xteink. GUI menampilkan progres detail serta perbandingan halaman PDF asli dengan tampilannya di e-reader sebelum file diunduh.

Mesin PDF yang dipakai adalah Docling, ditambah tahap perbaikan buatan sendiri. Semua proses berjalan di mesin pengguna, dan buku tidak pernah keluar dari komputer. Repo disiapkan untuk dirawat bersama oleh orang lain dan agen AI dari mesin yang berbeda.

## 2. Tujuan dan alasan

Pemilik memakai e-reader Xteink, yang hanya membaca EPUB, TXT, dan XTC/XTCH. Tool ini mendukung semua model Xteink (dipilih pengguna) dan e-reader umum. Banyak bacaannya berbentuk PDF:

- buku teknis keamanan (forensik, malware, threat hunting) yang penuh listing kode, diagram, dan tabel;
- buku nonfiksi berbahasa Indonesia, sebagian hasil scan.

PDF tidak bisa dibaca nyaman di layar 4,3" berukuran 480×800. Tool yang sudah ada, yaitu [epubkit](https://github.com/b1rdmania/epubkit), [epub-to-xtc-converter](https://github.com/bigbag/epub-to-xtc-converter), dan optimizer bawaan CrossPoint, hanya mengoptimalkan EPUB yang sudah ada. Belum ada tool yang mengubah PDF atau Markdown langsung menjadi EPUB/XTC siap Xteink dalam satu langkah.

Ini tool pribadi pemilik yang akan dirawat bersama orang lain dan agen AI.

## 3. Goals

- **G1.** PDF apa pun menjadi EPUB reflow yang enak dibaca. Cakupannya: PDF digital 1–2 kolom, PDF scan (OCR bahasa Indonesia dan Inggris), kode, gambar, tabel, rumus, catatan kaki, dan halaman kosong.
- **G2.** Markdown menjadi EPUB.
- **G3.** Optimizer EPUB untuk e-reader umum (`general`) atau model Xteink pilihan pengguna (X4, X4 Pro, X4 v2 Classic, X3), termasuk kompresi. Optimizer ini juga berlaku untuk EPUB yang sudah ada, misalnya EPUB penerbit.
- **G4.** Output XTC/XTCH. Halamannya sudah dirender, jadi gambar tetap tampil walaupun device memakai firmware bawaan.
- **G5.** Dua antarmuka di atas inti yang sama:
  - CLI;
  - GUI web dengan progres detail dan perbandingan PDF asli dengan preview e-reader.
- **G6.** Mudah di-install (satu perintah) dan di-deploy (satu image Docker). Mudah dirawat: satu bahasa, dependency sedikit dan dikunci, tes serta CI di 3 OS.
- **G7.** Lokal dan privat. Konversi berjalan tanpa koneksi jaringan. Internet hanya dipakai saat mengunduh model AI, dan itu pun setelah pengguna menyetujui ukurannya.
- **G8.** Transparan. Setiap konversi menghasilkan daftar temuan (apa yang di-OCR, diperbaiki, atau dijadikan gambar, serta peringatan), dan setiap temuan bisa dibuka langsung di preview.
- **G9.** Siap kolaborasi. Repo memuat aturan kerja untuk manusia dan agen AI (Claude Code, Codex, Cursor) beserta plugin **ponytail** dan **antislop**.
- **G10.** Gaya halaman XTC bisa diatur setara xtctool.com, dengan live preview (§8.18).

## 4. Non-goals (versi pertama)

- Layanan online publik, akun, atau multi-pengguna.
- Mac Intel dan Windows ARM native.
- Membuka DRM. EPUB ber-DRM ditolak dengan pesan yang jelas.
- Format KEPUB, AZW3, dan MOBI; mengirim file ke device lewat Wi-Fi.
- Fidelitas sempurna untuk layout bebas seperti majalah atau poster. Untuk itu ada mode gambar halaman.
- Rumus sebagai MathML/LaTeX. Rumus dijadikan gambar, dan model rumus Docling (640 MB) tidak dipakai.
- Editor teks di GUI. Koreksi hasil OCR dilakukan lewat file Markdown (§8.5).
- Preview EPUB yang identik piksel dengan firmware. Preview EPUB berupa perkiraan dan diberi label begitu.
- Nomor halaman stabil khusus CrossInk (`META-INF/x-locations.json`). Ditunda ke versi berikutnya.

## 5. Anti-goals: gagal walaupun "jalan"

- Isi buku terkirim ke luar mesin, baik lewat upload, telemetri, CDN, maupun API.
- File yang tidak bisa dibuka, lambat, atau crash di Xteink, misalnya karena progressive JPEG, gambar raksasa, font tertanam, atau bab raksasa.
- Isi hilang tanpa peringatan: kode digabung jadi satu baris, paragraf hilang, atau urutan baca salah tanpa temuan di laporan.
- Install yang rapuh atau berat di Windows/Linux, misalnya Linux mengunduh CUDA 3,3 GB tanpa diminta.
- Mengunduh data besar tanpa menyebutkan ukurannya dan tanpa meminta persetujuan.
- UI yang generik ala AI, atau GUI yang membingungkan. Setiap tahap hanya punya satu tombol utama.

## 6. Batasan

### 6.1 Device Xteink

| Model | Layar (portrait) | Prosesor / RAM | Catatan |
|---|---|---|---|
| X4 | 480×800, 4,3", ~220 PPI | ESP32-C3, ~380 KB RAM usable | |
| X4 Pro | 480×800 | ESP32-S3 + 8 MB PSRAM | layar sentuh, front light, progressive JPEG didukung |
| X4 v2 Classic | 480×800 | ESP32-S3 + PSRAM | |
| X3 | 528×792, 3,7" | ESP32-C3 | |

Semua model memakai layar 4 tingkat abu-abu (sumber: dokumentasi Papyrix).

- **Firmware bawaan** tidak menampilkan gambar di dalam EPUB sama sekali (diuji epubkit di X3 dan X4). Gambar hanya bisa tampil lewat XTC.
- **CrossPoint dan fork-nya** (CrossInk, Papyrix) punya batasan berikut:
  - Hanya mendukung JPEG baseline (SOF0/SOF1), PNG, dan BMP. Progressive JPEG tampil sebagai placeholder di X4/X3, dan JPEG arithmetic ditolak.
  - GIF, SVG, WebP, dan TIFF tidak didukung. Gambar di bawah 20 px dan gambar `data:` URI dilewati. Batas decode 2048×3072.
  - Ukuran EPUB idealnya di bawah 20 MB.
  - Font tertanam dan CSS `float`, `flex`, `grid`, atau `position` bermasalah. Bab yang sangat besar memperlambat device.
- Pengguna memilih model device di tool. Output dibuat aman untuk semua model (JPEG baseline, batas memori ESP32-C3), jadi tiga model 480×800 saat ini menghasilkan file yang sama.
- Belum diketahui apakah firmware bawaan X4 Pro dan X4 v2 Classic menampilkan gambar EPUB.

### 6.2 Platform dan syarat minimum

Versi OS diambil dari wheel yang benar-benar dipakai. Angka RAM berasal dari spike.

| | macOS | Windows | Linux |
|---|---|---|---|
| Sistem | 14+ Apple Silicon | 10/11 x64 | x64, glibc 2.28+ (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| RAM | 8 GB (puncak OCR ~3,2 GB) | sama | sama |
| Disk | ~3 GB | ~3 GB | ~3 GB (dengan PyTorch versi CPU) |
| Download pertama | ~0,9 GB (paket ~0,35 + model ~0,57) | ~1 GB | ~1,1 GB, **wajib** PyTorch versi CPU |
| GPU | opsional (GPU Apple dipakai otomatis) | opsional | opsional |

### 6.3 Lisensi dependency

Hanya lisensi permisif yang dipakai: Docling (MIT), pypdfium2 (Apache-2.0/BSD-3), Pillow (MIT-CMU), Typst Python (Apache-2.0), markdown-it-py (MIT), FastAPI (MIT), Jinja2 (BSD-3), huggingface_hub (Apache-2.0), onnxruntime (MIT), fontTools (MIT).

- Hindari AGPL (PyMuPDF, ebooklib) dan GPL (Calibre, pandoc, CREngine).
- Model diunduh saat runtime dan tidak disimpan di repo.
- Font yang dibundel berlisensi OFL (Literata, Bitter, Lexend Deca, dalam instance statis), dan file lisensinya ikut disertakan. Font unggahan pengguna hanya disimpan di folder job.

### 6.4 Jaringan (temuan spike)

- Di jaringan pemilik, koneksi IPv6/NAT64 sesekali me-reset TLS.
- Pengunduh `hf-xet` milik Hugging Face macet total karena tidak bisa dipaksa ke IPv4.
- Unduhan dari Hugging Face lambat (125 KB/s–1,4 MB/s).

Karena itu pengunduh model harus tangguh (§8.14).

### 6.5 Privasi dan keamanan

- Konversi berjalan tanpa jaringan, dan ini dibuktikan oleh tes.
- GUI tidak memuat aset dari CDN atau dari luar.
- Server web hanya bisa diakses dari mesin itu sendiri, kecuali pengguna mengaktifkan mode jaringan yang wajib memakai token.
- Model hanya diterima dalam format data (`.safetensors`, `.onnx`, `.npz`). Pickle tidak diterima.
- Dependency dikunci dengan hash dan diperiksa ke database kerentanan.

## 7. Pendekatan yang dipertimbangkan

### 7.1 Arsitektur dasar (dipilih: A)

| | Pendekatan | Keputusan |
|---|---|---|
| **A** | Aplikasi Python lokal dengan mesin AI tata letak dokumen | **Dipilih.** Satu-satunya yang mendekati "semua PDF" (OCR, kolom, tabel, kode). |
| B | Calibre sebagai mesin | Ditolak: tidak ada OCR, lemah di kolom/tabel/rumus, GPL, install berat. |
| C | Web app murni di browser (pdf.js + Tesseract.js), seperti dua referensi | Ditolak: tidak ada mesin layout yang bagus di browser, OCR lambat dan kurang akurat. |
| D | Server online dengan GPU | Ditolak: biaya hosting, dan buku harus di-upload. |

### 7.2 Mesin PDF (dipilih: Docling, disetujui pemilik setelah spike)

| | Docling | Marker |
|---|---|---|
| Teks digital vs EPUB penerbit | 99,4% / 99,7% | 99,4% / 99,7% |
| OCR scan Indonesia (hal. 87) | 99,0% | 100% |
| Blok kode | terdeteksi; baris bisa dipulihkan | jadi tabel atau paragraf |
| Gambar | diekstrak | tidak diekstrak |
| Halaman kosong | aman | crash (bug) |
| Rumus | penanda saja, tapi bisa dipotong jadi gambar | LaTeX |
| Urutan baca 2 kolom | salah 1 halaman, diperbaiki dengan XY-cut | benar |
| Lisensi | MIT | bobot model terbatas (OpenRAIL-M) |

Detail lengkap ada di [spike](../../research/2026-11-16-spike-pdf-engines.md).

### 7.3 GUI (dipilih: A)

| | Pendekatan | Keputusan |
|---|---|---|
| **A** | FastAPI + template HTML (Jinja2) + JavaScript biasa, tanpa tahap build | **Dipilih.** Satu bahasa, mudah dirawat agen dan manusia, sama persis di laptop dan Docker. |
| B | Gradio | Ditolak: panel perbandingan dan bingkai device sulit dibuat, dependency berat dan sering berubah, tampilan generik. |
| C | SPA React/Vue + API | Ditolak: butuh Node dan tahap build, sehingga install dan perawatan lebih sulit. |

Tata letak GUI disetujui pemilik lewat mockup: gabungan A+B+C, yaitu satu ruang kerja yang berubah sesuai tahap (§8.13).

## 8. Desain

### 8.0 Urutan rilis (usulan saya)

Setiap milestone menghasilkan sesuatu yang bisa langsung dipakai. Setiap milestone punya rencana implementasinya sendiri.

1. **M1: Inti + CLI.**
   - Input PDF, Markdown, atau EPUB menjadi EPUB yang dioptimalkan (umum atau model Xteink) dan dikompres.
   - Termasuk folder buku yang bisa diedit, setup model, dan laporan temuan.
   - Termasuk setup kolaborasi repo (§8.16) dan CI.
   - **Hasil pertama yang bisa dipakai:** pemilik mengonversi PDF lalu membacanya di device.
2. **M2: GUI web + preview.** Termasuk renderer halaman Typst (gambar PNG seukuran layar) untuk preview EPUB perkiraan dengan pemilih "View as" (Stock / CrossPoint / CrossInk), serta mekanisme live preview (§8.18).
3. **M3: Output XTC/XTCH.** Kuantisasi 1-bit/2-bit, encoder + decoder XTC/XTCH, preview XTC yang identik di GUI, dan panel gaya halaman XTC lengkap dengan live preview (§8.18).
4. **M4: Docker + rilis** (image GHCR, catatan rilis).

Pemilik memutuskan GUI dikerjakan sebelum XTC, karena GUI dan preview yang paling diutamakan.

**Uji di device ditunda** (keputusan pemilik).
- Nilai bertanda "verifikasi di device" (batas ukuran bab, dukungan CSS `pre-wrap`/tabel, header XTC) memakai nilai sementara yang aman dan dicatat di `docs/decisions.md`.
- Nilai itu dikunci setelah pemilik menguji. Rencana implementasi menyertakan tugas "verifikasi di device" di akhir, yang dijalankan pemilik.

### 8.1 Gambaran sistem

```
                ┌──────────── CLI (eco ...) ────────────┐
                │                                        │
                ├──────────── GUI web (eco web) ────────┤
                ▼                                        ▼
        ┌────────────────────── inti (pipeline) ──────────────────────┐
PDF ──▶ │ 1 periksa halaman  2 Docling  3 tahap perbaikan  ──▶ buku   │
MD  ──▶ │                                       (folder Markdown) ──┐ │
EPUB ─▶ │ 4 pembuat EPUB ──▶ 5 optimizer + kompresi ──▶ EPUB        │ │
        │ 6 renderer halaman (Typst) ──▶ XTC/XTCH + gambar preview ◀┘ │
        │ temuan + peta halaman (sumber → device) untuk GUI           │
        └─────────────────────────────────────────────────────────────┘
```

Inti adalah library tanpa urusan CLI atau web. CLI dan GUI hanya memanggil inti.

### 8.2 Inti: kontrak pipeline

- Satu pintu masuk, misalnya `convert(job, on_event, cancel) -> Result`. Nama persisnya diserahkan ke builder.
  - `job` berisi input dan opsi: model device, format, ukuran file, firmware, mode, OCR, dan tipografi XTC.
  - `on_event` menerima event berikut:
    - tahap mulai/selesai;
    - progres halaman `i/n` beserta perkiraan sisa waktu;
    - temuan `{halaman, jenis, tingkat, pesan}`;
    - selesai/gagal.
  - **Setiap konversi berjalan di proses pekerja terpisah** (usulan saya setelah builder check). Pembatalan menghentikan proses itu dalam ≤ 10 dtk lalu membersihkan file sementara. Event dikirim ke CLI/GUI lewat antrean antarproses. Biayanya, model dimuat ulang per job (±5 dtk). Ini sepadan, karena potongan 25–50 halaman hasil scan bisa makan 50–100 dtk dan terlalu kasar untuk pembatalan cepat.
- `Result` berisi:
  - path output;
  - laporan (`report.json`);
  - indeks preview: gambar halaman sumber, gambar halaman device per format, dan peta halaman sumber → device.
- **Cache ekstraksi.** Hasil ekstraksi (folder buku) dikunci dengan hash file, versi ekstraktor, dan opsi yang relevan. Mengubah opsi output, seperti format, model device, atau ukuran huruf, tidak mengulang Docling atau OCR. Dengan begitu tombol "Ubah pengaturan" di GUI bisa langsung membangun ulang hasilnya.

### 8.3 Ekstraksi PDF (Docling)

- Semua panggilan Docling dibungkus dalam **satu modul adaptor**, karena API Docling sering berubah (contohnya CLI yang kini memakai `docling convert`). Versi Docling dipin.
- Konfigurasi:
  - OCR otomatis untuk halaman atau area tanpa teks, memakai RapidOCR dengan `onnxruntime`. **`onnxruntime` wajib dicantumkan eksplisit** karena tidak ikut terpasang bersama Docling.
  - Struktur tabel aktif dan gambar diekstrak.
  - Model diambil dari folder lokal (`artifacts_path`) dalam mode offline.
- Mode OCR memakai default Docling. Mode `full_page` tidak dipakai: memang membuat judul bersih, tapi merusak teks miring (spike). Opsi `--ocr force` disediakan untuk PDF yang lapisan teksnya rusak.
- Buku tebal diproses per potongan halaman untuk membatasi RAM. Ukuran potongan diserahkan ke builder. Progres dilaporkan per halaman bila Docling menyediakan callback; jika tidak, potongan diperkecil untuk halaman OCR. Pembatalan lewat proses pekerja (§8.2). Setiap blok menyimpan halaman asal dan bbox-nya.

### 8.4 Tahap perbaikan

Setiap tahap berupa fungsi kecil atas model buku yang punya data halaman asal. Setiap tahap mencatat temuan dan punya tes sendiri.

1. **Urutan baca.**
   - Untuk setiap halaman, deteksi multi-kolom: ada dua kelompok blok teks atau lebih yang dipisahkan celah vertikal.
   - Jika multi-kolom, terapkan XY-cut rekursif: potong pita horizontal dulu, lalu kolom. Jika bukan, pakai urutan Docling.
   - Furnitur halaman (header/footer, stempel) dibuang.
   - Terbukti memperbaiki halaman 1 paper ResNet.
2. **Blok kode.**
   - Di halaman yang punya lapisan teks, teks diambil ulang dari PDF berdasarkan bbox (pypdfium2 `get_text_bounded`). **Offset CropBox wajib ditambahkan.**
   - Indentasi direkonstruksi dari posisi x karakter.
   - Jika hasilnya kosong, teks Docling dipakai dan dicatat sebagai temuan.
   - Di halaman hasil OCR, blok kode dipotong sebagai gambar.
3. **Rumus.** Item `formula` dipotong dari halaman PDF (~216 dpi, abu-abu, padding 4 pt) dan dimasukkan sebagai gambar dengan alt "rumus". Rumus di tengah kalimat belum ditangani (batasan yang diketahui).
4. **Tabel.** Tabel menjadi tabel HTML. Pada target Xteink, tabel yang terlalu lebar untuk layar dipotong dari PDF sebagai gambar. Builder menentukan aturannya, misalnya lebih dari 4 kolom atau perkiraan lebar minimum melebihi layar.
5. **Gambar.** Gambar diambil dengan resolusi sumber. Keterangan gambar ditautkan ke gambarnya (`figure` dan `figcaption`).
6. **Pembersihan teks.**
   - Sambung pemenggalan kata di akhir baris (`seper– tinya` → `sepertinya`), dengan syarat kata gabungannya muncul di bagian lain buku atau potongannya bukan kata utuh.
   - Bersihkan artefak OCR: token satu huruf yang sama dengan huruf terakhir kata sebelumnya, dan huruf yang menempel di depan kata dengan pola yang sama (`Fungsi iPositif f Rayuan` → `Fungsi Positif Rayuan`).
   - Normalisasi spasi, ligatur, dan Unicode NFC.
7. **Struktur bab.**
   - Pakai bookmark PDF jika ada. Sampel digital punya 191–715 bookmark dengan 3–4 tingkat. Judul dan halaman bookmark dicocokkan dengan blok judul terdekat, dan tingkatnya diambil dari kedalaman bookmark.
   - Jika tidak ada bookmark, misalnya pada buku scan, pakai heuristik: judul HURUF BESAR menjadi tingkat 1, sisanya tingkat 2.
8. **Catatan kaki.** Disimpan di akhir bagiannya sebagai teks kecil. Penautan ke penandanya ditunda ke versi berikutnya.
9. **Halaman khusus.** Halaman kosong dilewati. Halaman yang tidak bisa di-reflow (gambar menutup sebagian besar halaman dan teksnya sedikit, seperti komik atau diagram penuh) dijadikan gambar utuh. Ambang batasnya diserahkan ke builder.

### 8.5 Format tengah: folder buku Markdown

```
<nama>.book/
  book.md           # front matter YAML (title, author, language, cover, source) + isi
  images/           # gambar, rumus, kode-sebagai-gambar, tabel (bentuk gambar), halaman
  report.json
```

Keputusan berikut adalah usulan saya setelah builder check:

- **Format:** CommonMark + tabel GFM + front matter. **HTML mentah boleh dipakai** untuk hal yang tidak bisa diungkapkan GFM, misalnya tabel dengan `colspan`/`rowspan`, `figure` + `figcaption`, dan blok catatan kaki. `#` menandai bab (titik pecah file), `##` dan seterusnya menandai bagian. Kode memakai fence.
- **Penanda halaman sumber** ditulis sebagai komentar HTML `<!-- page: 268 -->` di antara blok. Tidak ada file `source-map.json`. Sinkronisasi preview bekerja per halaman dan tetap jalan setelah `book.md` diedit, selama penandanya tidak dihapus.
- **Folder buku berdiri sendiri.**
  - Setiap tabel disimpan dalam dua bentuk: HTML di `book.md` dan gambar yang sudah dipotong di `images/`. Saat build, target menentukan bentuk mana yang dipakai.
  - Rumus, kode-sebagai-gambar, dan cover juga sudah dipotong saat ekstraksi.
  - `eco convert <nama>.book/` tidak butuh PDF asli.
  - Front matter `source` mencatat nama file dan sha256 PDF. Panel "asli" di GUI memakai salinan PDF milik job jika ada; jika tidak ada, panel itu menampilkan "PDF asli tidak tersedia".
- Tahap §8.4 butir 1–3 dan 5–9 berjalan **sebelum** cache saat ekstraksi. Butir 4, yaitu pemilihan bentuk tabel, berjalan saat build.
- Pemilik bisa mengedit `book.md`, misalnya untuk mengoreksi hasil OCR, lalu menjalankan `eco convert <nama>.book/`.
- `eco extract` hanya membuat folder ini, sedangkan `eco convert file.pdf` langsung sampai EPUB/XTC (folder buku disimpan di cache).

### 8.6 Input lain

- **`.md` atau folder buku:** langsung ke pembuat EPUB dan renderer. Di GUI, panel "asli" menampilkan Markdown.
- **`.epub`:** langsung ke optimizer. DRM dideteksi lewat `META-INF/encryption.xml` atau `rights.xml` selain obfuscation font, lalu ditolak.
  - Untuk XTC dan preview, XHTML penerbit diubah ke model buku **sebatas yang wajar** (usulan saya): judul, paragraf, daftar, `pre`/kode, gambar, tabel, penekanan, dan tautan.
  - Elemen lain diratakan menjadi teks dan dicatat sebagai temuan.
  - Ini tidak termasuk kriteria akurasi di §9, cukup tes unit dengan EPUB fixture buatan sendiri.

### 8.7 Pembuat EPUB

- Paket EPUB 3 dengan `nav.xhtml` dan `toc.ncx` (supaya kompatibel dengan pembaca lama).
- Satu XHTML per bab. Bab panjang dipecah supaya tidak melewati batas ukuran (awal 100 KB; diverifikasi di device).
- Metadata:
  - `dc:title`, `dc:creator`, `dc:language` (dari front matter atau flag, atau deteksi sederhana id/en);
  - `dc:identifier` berupa UUID dari hash sumber (stabil antar-build);
  - `dcterms:modified`;
  - cover memakai `properties="cover-image"` dan `<meta name="cover">`.
- Cover PDF diambil dari render halaman 1. Untuk Markdown tanpa cover, dibuat cover teks sederhana dengan font bawaan.
- Struktur zip: entri `mimetype` pertama dengan mode STORED, entri lain DEFLATE level 9, tanpa file sampah.
- Divalidasi dengan EPUBCheck di CI.

### 8.8 Optimizer dan kompresi (untuk EPUB apa pun)

| Langkah | `general` | Xteink (semua model) |
|---|---|---|
| Gambar | warna dipertahankan, sisi terpanjang maks. 1600 px, JPEG baseline q≈85, PNG dioptimalkan | abu-abu, dimuat ke layar model: 480×800, atau 528×792 untuk X3 (tidak diperbesar), alfa diratakan putih, foto JPEG baseline q≈80, line art PNG abu-abu (builder mengukur dan memilih) |
| Format tak didukung | GIF/WebP/TIFF → JPEG/PNG | sama; pembungkus SVG cover dibuka; SVG lain dirasterisasi bila ada rasterizer permisif berbasis wheel, jika tidak ada dibuang + temuan |
| `data:` URI | diekstrak jadi file | sama |
| Gambar < 20 px | dibiarkan | dibuang |
| Font | di-subset (fontTools); jika gagal, dibiarkan | dibuang beserta `@font-face` |
| CSS | dibiarkan | buang `float`, `position`, `flex`/`grid`, `columns`; sisipkan CSS e-ink (gambar maks. 100%, `pre` dibungkus, tabel sederhana) |
| Bab besar | dibiarkan | dipecah |
| Zip | deflate 9; manifest tak terpakai dan file OS dibuang | sama |

- **Preset "Ukuran file"** (`--size`, usulan saya) mengatur parameter gambar di atas. Target menentukan ukuran layar; preset menentukan kualitasnya.

  | Preset | `general` | Xteink |
  |---|---|---|
  | `small` ("Paling kecil") | JPEG q≈65, sisi terpanjang maks. 1200 px | JPEG q≈65; jika firmware = bawaan, gambar **dibuang** (memang tidak akan tampil) + temuan |
  | `balanced` ("Seimbang", default) | seperti tabel di atas | seperti tabel di atas |
  | `best` ("Kualitas terbaik") | JPEG q≈92, sisi terpanjang maks. 2048 px | JPEG q≈92, PNG untuk semua line art |

- Laporan menampilkan ukuran sebelum dan sesudah per kategori.
- Target: EPUB penerbit *Threat Hunting* menyusut dari 5,29 MB ke ≤1 MB (estimasi spike 0,77 MB).
- Zopfli ditunda: tambahannya hanya beberapa persen. Ukur dulu.
- Jika firmware = bawaan, gambar tetap disimpan supaya file tetap berguna kalau firmware diganti, tapi laporan dan preview menandai bahwa gambar tidak akan tampil.

### 8.9 Renderer halaman (XTC/XTCH dan preview)

- Model buku diubah ke markup **Typst** dengan konverter sendiri. Tidak boleh ada paket Typst yang diunduh saat render. Jika butuh paket, paket itu di-vendor.
- **Ukuran halaman:**
  - X4, X4 Pro, dan X4 v2 Classic: 480×800 px. Halaman Typst diatur dalam pt dengan PNG pada ppi 72, sehingga 1 pt = 1 px.
  - X3: 528×792 px.
- **Tipografi default** (bisa diatur di "Advanced settings"):
  - font teks OFL yang dibundel (usulan: Literata) dan font kode OFL monospace;
  - ukuran ±32 px, margin ±16 px, jarak baris ±1,35;
  - rata kiri-kanan, dengan pemenggalan kata sesuai bahasa jika Typst mendukung (perlu dicek untuk `id`).
- **Bilah status** di bawah halaman: judul bab dan nomor halaman/total.
- **Kuantisasi:**
  - XTH (4 tingkat): gambar memakai Floyd–Steinberg, teks antialias dipetakan ke 4 tingkat.
  - XTG (1-bit): teks memakai ambang batas, gambar memakai dithering.
  - Default output: **XTCH**.
- **Encoder XTG/XTH/XTC/XTCH** mengikuti [spesifikasi bigbag](https://github.com/bigbag/epub-to-xtc-converter/blob/main/docs/xtc-format-spec.md), yang diturunkan dari [gist CrazyCoder](https://gist.github.com/CrazyCoder/b125f26d6987c0620058249f59f1327d). Isinya:
  - header;
  - metadata judul/penulis;
  - tabel bab (halaman diambil lewat Typst query);
  - indeks halaman;
  - data.

  Encoder dilengkapi decoder untuk tes round-trip. Versi header berbeda antar-fork, jadi ikuti spesifikasi bigbag dan verifikasi di device pemilik.
- **Preview:**
  - Untuk XTC, gambar halaman dari renderer ini **adalah** preview-nya (identik).
  - Untuk EPUB, renderer yang sama dipakai dengan pengaturan "perkiraan firmware". Pemilih **View as** (Stock / CrossPoint / CrossInk) di panel preview menentukan perkiraan yang ditampilkan. Pada Stock, gambar disembunyikan dan diberi tanda. Preview ini diberi label "perkiraan".
- **Peta halaman:** renderer mencatat halaman sumber dari blok-blok di setiap halaman device (lewat label Typst dan query). Peta ini dipakai GUI untuk menyinkronkan kedua panel.

### 8.10 Mode gambar halaman

- Bisa untuk seluruh buku (`--mode pages`) atau per halaman secara otomatis (§8.4 butir 9).
- Caranya:
  1. Render halaman dengan resolusi tinggi.
  2. Potong margin putih.
  3. Skalakan ke lebar layar.
  4. Jika lebih tinggi dari layar, potong jadi irisan yang sedikit tumpang tindih (~5%).
- Ada opsi landscape: diputar 90° sehingga lebarnya 800.
- Outputnya berupa halaman XTC, atau EPUB dengan satu gambar per layar.

### 8.11 Temuan dan laporan

- Setiap temuan berbentuk `{halaman, jenis, tingkat: info|peringatan, pesan}`. Pesannya dalam bahasa Inggris yang sederhana, misalnya "Wide table converted to an image to fit the screen".
- Jenis temuan minimal:
  - halaman kosong;
  - kode dipulihkan atau dijadikan gambar;
  - rumus, tabel, atau halaman dijadikan gambar;
  - urutan baca diperbaiki;
  - halaman di-OCR;
  - OCR kurang yakin (jika Docling menyediakan skor);
  - gambar atau font dibuang;
  - bab dipecah.
- Temuan disimpan di `report.json`. CLI mencetak ringkasannya. Di GUI, temuan tampil sebagai daftar yang bisa diklik untuk melompat ke halaman di kedua panel.

### 8.12 CLI

```
eco setup   [--yes] [--ipv4]
eco convert INPUT... [-o DIR] [--device x4|x4-pro|x4-classic|x3|general]
            [--firmware any|stock|crosspoint|crossink]
            [--format epub,xtch|xtc] [--size small|balanced|best]
            [--mode auto|reflow|pages] [--ocr auto|force|off]
            [--title T] [--author A] [--lang id|en] [--font-size N]
eco extract INPUT.pdf [-o DIR]
eco web     [--host 127.0.0.1] [--port 8000] [--data DIR] [--token T] [--no-browser]
```

- `INPUT` bisa berupa `.pdf`, `.md`, folder buku, `.epub`, atau folder berisi file-file tersebut (batch). Jika satu file gagal, file lain tetap jalan dan ringkasan ditampilkan di akhir.
- Default: `--device x4 --firmware any --format epub --size balanced`.
- `--firmware` tidak mengubah file EPUB, kecuali `--size small` + `stock`, yang membuang gambar. Pilihan ini hanya memengaruhi saran di laporan dan preview.

### 8.13 GUI web

**Tata letak (disetujui):** satu ruang kerja dengan penanda tahap *Pilih file → Atur → Proses → Cek & unduh*. Mockup acuan ada di [`docs/design/gui-layout.html`](../../design/gui-layout.html). Isinya sudah disanitasi: tanpa isi buku berhak cipta. Teks di mockup masih berbahasa Indonesia; UI final berbahasa Inggris. Isinya berganti sesuai tahap:

1. **Pilih file dan atur.**
   - Area seret-lepas dan daftar file. Setiap file menampilkan jumlah halaman, jenis (digital atau scan), dan perkiraan waktu.
   - Pengaturan inti cukup **tiga**: model device, file yang dibuat (EPUB/XTC), dan ukuran file. Firmware dan pengaturan lain disembunyikan di "Advanced settings". Mockup masih menampilkan empat; versi tiga ini yang berlaku.
   - Satu tombol utama: "Mulai konversi".
   - Teks "Everything is processed on this computer".
2. **Proses.**
   - Bilah progres per file: halaman i dari n dan sisa waktu.
   - Enam tahap kerja yang dicentang satu per satu.
   - Daftar temuan yang muncul langsung, antrean file berikutnya, dan tombol "Batalkan".
3. **Cek dan unduh.**
   - Ringkasan: waktu, ukuran sebelum dan sesudah, dan jumlah peringatan.
   - Tombol unduh EPUB/XTC dan "Ubah pengaturan" (membangun ulang tanpa OCR ulang).
   - Daftar temuan di kiri, PDF asli di tengah, preview e-reader di kanan dengan pilihan EPUB/XTC dan pemilih "View as" (Stock / CrossPoint / CrossInk). Kedua panel bergerak bersama, dan mengklik temuan membuat keduanya lompat ke halaman itu.

**Teknologi:**
- FastAPI, template Jinja2, CSS, dan **JavaScript biasa tanpa tahap build**.
- **Semua aset lokal, tanpa CDN.** CSP: `default-src 'self'`.
- Progres dikirim lewat Server-Sent Events.

**Endpoint (sketsa; builder bebas menyesuaikan):**
- `POST /jobs` (upload + opsi), `GET /jobs/{id}`, `GET /jobs/{id}/events` (SSE), `POST /jobs/{id}/cancel`
- `POST /jobs/{id}/rebuild`
- `GET /jobs/{id}/source/{hal}.png`, `GET /jobs/{id}/preview/{format}/{hal}.png`, `GET /jobs/{id}/download/{format}`
- `GET /setup` (status dan ukuran model), `POST /setup/download` (dengan progres)

**Cara kerja job:**
- Antrean di dalam proses, satu konversi pada satu waktu. Tidak memakai Celery atau Redis.
- Job disimpan di folder data, jadi tetap terlihat setelah restart.
- Job lebih dari 7 hari dihapus otomatis, dan bisa juga dihapus manual.
- Batas upload bisa diatur (default 500 MB).

**Keamanan:**
- Default bind ke `127.0.0.1` tanpa token.
- Jika `--host` bukan loopback, **token wajib**. Jika tidak diberikan, token dibuat otomatis dan dicetak saat start.

**Lain-lain:**
- Aksesibilitas dasar: navigasi keyboard, label, dan kontras cukup.
- UI berbahasa Inggris (keputusan pemilik), dengan semua teks dikumpulkan di satu modul.
- Arah visual di `DESIGN.md` (diwajibkan antislop): **gaya B, netral dan bersih**, dipilih pemilik.
  - Latar abu-abu terang, panel putih, dan satu warna aksen biru.
  - Huruf sistem.
  - Bingkai device gelap dengan layar e-ink terang sebagai pusat perhatian.

### 8.14 Model AI: setup, unduhan tangguh, offline

- `eco setup`, atau halaman setup di GUI:
  - menampilkan daftar model dan ukurannya, yang dihitung dari Hugging Face saat itu (layout ~172 MB, tabel ~213 MB, OCR ~32 MB);
  - menampilkan totalnya, lalu **meminta persetujuan**;
  - opsi `--yes` untuk otomatisasi.
- Cara mengunduh:
  - `huggingface_hub` dengan `HF_HUB_DISABLE_XET=1` sebagai default dan timeout 20 dtk;
  - coba ulang sambil melanjutkan unduhan yang terputus;
  - opsi `--ipv4`;
  - revisi model dipin ke commit SHA;
  - **daftar format yang diizinkan**: `.safetensors`, `.onnx`, `.npz`, serta file teks/konfigurasi. Pickle ditolak.
- Model disimpan di folder data aplikasi (`platformdirs`) atau `/data` di Docker.
- Saat konversi, mode offline aktif (`HF_HUB_OFFLINE=1` dan `artifacts_path`). Jika model belum ada, muncul pesan jelas yang mengarahkan ke `eco setup`.

### 8.15 Instalasi dan deploy

- **Lokal:**
  1. `uv tool install git+https://github.com/<pemilik>/<repo>` (`uv` sekaligus menyiapkan Python).
  2. `eco setup`.
  3. `eco web` atau `eco convert`.

  README memuat langkah per OS. Di Linux, PyTorch harus versi CPU, lewat indeks CPU di `[tool.uv.sources]` atau flag `--torch-backend cpu`. Builder **wajib memverifikasi** bahwa `uv tool install` mematuhi pengaturan ini; jika tidak, dokumentasikan flag-nya.
- **Docker:**
  - Base `python:3.12-slim` + uv + PyTorch CPU.
  - Contoh: `docker run -p 8000:8000 -v eco-data:/data -e ECO_TOKEN=... <image>`.
  - Model diunduh lewat halaman setup GUI saat pertama dijalankan, jadi image tetap kecil. Ada build-arg opsional untuk menanam model bagi server offline.
  - Image dipublikasikan ke GHCR oleh GitHub Actions saat ada tag versi.
- Versi mengikuti SemVer, dan catatan rilis ditulis di GitHub Releases.

### 8.16 Kolaborasi dan perawatan

**Isi repo:**

```
src/eco/            inti, adaptor (docling, typst), cli, web (templates/, static/)
fonts/              font OFL + lisensinya
tests/              unit, integrasi (slow), acceptance (sampel lokal)
docs/               design, riset, catatan keputusan (docs/decisions.md)
.claude/settings.json  marketplace + plugin ponytail & antislop
.github/            workflow CI & rilis, template PR, Dependabot
AGENTS.md  CLAUDE.md  CONTRIBUTING.md  DESIGN.md  README.md  README.id.md  LICENSE (MIT)
pyproject.toml  uv.lock  .python-version  Dockerfile  .gitignore
```

**Peran file kolaborasi:**
- `AGENTS.md` adalah sumber kebenaran untuk agen apa pun dan juga manusia. Isinya:
  - peta arsitektur;
  - perintah `uv sync`, `uv run pytest`, `uv run ruff check`, dan `uv run ruff format`;
  - konvensi;
  - aturan ponytail dan antislop, termasuk cara memasang antislop di Codex/Cursor;
  - larangan meng-commit `samples/`;
  - cara menjalankan tes acceptance.
- `CLAUDE.md` berisi `@AGENTS.md` plus hal khusus Claude.
- `.claude/settings.json` memuat:
  - `extraKnownMarketplaces`: `ponytail` (`DietrichGebert/ponytail`) dan `anti-slop` (`miqdadbadjuber/anti-slop`);
  - `enabledPlugins`: `ponytail@ponytail` dan `antislop@anti-slop`.

  Dengan begitu, siapa pun yang membuka repo di Claude Code akan diminta memasang kedua plugin itu.
- `CONTRIBUTING.md` menjelaskan alur kerja: branch → PR → CI hijau → review. Branch protection dan required checks diatur pemilik di GitHub.

**Tooling dan lingkungan:**
- Lingkungan identik di semua mesin lewat `uv.lock` dan `.python-version` (3.12).
- Tooling: ruff dan pytest. Tidak ada build step frontend.
- Dependabot berjalan mingguan. CI menjalankan OSV atau pip-audit.

**Aturan kode:**
- Modul kecil dengan batas jelas. Inti tidak tahu soal web atau CLI.
- Docling dan Typst diakses hanya lewat adaptor.
- Keputusan baru dicatat singkat di `docs/decisions.md`.

**Bahasa (keputusan pemilik):**
- Bahasa Inggris untuk kode, komentar, `AGENTS.md`, `CONTRIBUTING.md`, pesan commit, dan UI.
- README dua bahasa: `README.md` (Inggris) dan `README.id.md` (Indonesia), dijaga tetap sinkron.
- Design doc dan riset yang sudah ada tetap berbahasa Indonesia sebagai catatan keputusan.

**Repo (keputusan pemilik):**
- Publik di GitHub, lisensi MIT.
- Identitas git noreply GitHub khusus repo ini, sehingga email pribadi tidak ikut terlihat.
- Job CI gagal jika ada file PDF/EPUB ter-commit di luar `tests/fixtures/`, untuk berjaga-jaga kalau isi `samples/` bocor.

### 8.17 Pengujian

- **Unit (cepat, tanpa model)**:
  - setiap tahap perbaikan;
  - XY-cut;
  - penyambung pemenggalan kata;
  - pembersih artefak;
  - pengambilan ulang kode, dengan fixture PDF yang **CropBox-nya bergeser**;
  - pembuat EPUB;
  - aturan optimizer;
  - encoder XTC (round-trip + header);
  - argumen CLI;
  - API web dengan pipeline palsu (FastAPI TestClient).
- **Fixture sintetis** dibuat oleh kode sendiri: Typst menghasilkan PDF 2 kolom, kode, rumus, halaman kosong, dan pemenggalan kata. Halaman yang dirasterisasi menjadi PDF hasil scan. Dengan cara ini tidak ada masalah lisensi.
- **Integrasi (lambat, butuh model)**: Docling dijalankan pada fixture sintetis. Di CI, cukup satu job Linux dengan cache model. Kapan job ini jalan (per PR atau nightly) diserahkan ke builder.
- **Acceptance (lokal saja)**: memakai `samples/` milik pemilik, otomatis dilewati jika folder itu tidak ada. Ambang batasnya ada di §9.
  - **Kunci jawaban** ada di `samples/ground-truth/` (tidak di-commit; lihat `README.txt` di sana):
    - transkripsi halaman 87;
    - 14 judul halaman 80–92;
    - definisi metrik presisi/recall berurutan (difflib, blok ≥ 3 kata);
    - halaman uji kode (Forensic 105–117, Malware 262–274).
  - Paper ResNet ada di `samples/public/arxiv-1512.03385v1.pdf`.
- **Tanpa jaringan**: tes yang memblokir `socket.connect` lalu menjalankan konversi kecil.
- **CI**:
  - matriks ubuntu-latest, windows-latest, dan macos-14 (arm64) untuk unit tes dan ruff;
  - job EPUBCheck;
  - job OSV/pip-audit;
  - job build Docker.

### 8.18 Gaya halaman XTC dan live preview (ditambahkan 2026-11-17)

Disetujui pemilik. Fitur ini setara dengan pengaturan di [xtctool.com](https://xtctool.com/epub-to-xtc).

**Pengaturan gaya halaman (`PageStyle`)** berlaku penuh untuk XTC/XTCH. Untuk EPUB, pengaturan ini hanya dipakai sebagai simulasi di preview.

| Kelompok | Pengaturan | Default |
|---|---|---|
| Teks | font: Literata, Bitter, Lexend Deca (dibundel, OFL), Libertinus Serif (bawaan Typst), atau font unggahan (.ttf/.otf) | Literata |
| | ukuran (px) | 32 |
| | ketebalan, sesuai instance statis yang tersedia (400/500/600/700) | 400 |
| | jarak baris (%) | 135 |
| | margin (px) | 16 |
| | perataan: rata kiri-kanan atau rata kiri | rata kiri-kanan |
| | pemenggalan kata | aktif |
| | bahasa teks: otomatis dari buku atau pilih sendiri | otomatis |
| Gambar dan warna | mode: XTH (4 abu-abu) atau XTG (hitam-putih) | XTH |
| | dithering + kekuatan (0–100%), hanya di area gambar; teks dikuantisasi tanpa dithering supaya tetap tajam | aktif, 80% |
| | mode gelap (negatif) | mati |
| Progress bar | posisi atas/bawah, garis progres, halaman x/y, persen buku, halaman dan persen bab, penanda bab, lebar penuh, ukuran huruf, margin tepi dan samping | bawah; judul bab + halaman x/y |
| Device | model (X4, X4 Pro, X4 v2 Classic, X3) dan orientasi 0/90/180/270 | X4, 0 |

**Halaman per bab:** setiap bab dimulai di halaman baru. Karena itu render satu bab menghasilkan halaman yang sama persis dengan render seluruh buku.

**Live preview:**
- Ada di tahap "Cek & unduh". Tombol "Ubah pengaturan" membuka panel pengaturan di samping preview.
- Setiap kali pengaturan diubah, GUI meminta render ulang bab yang sedang dilihat, dengan jeda tunggu ±300 ms. Target: ≤ 1 dtk untuk bab ≤ 30 halaman di Mac M3.
- "Terapkan" membangun ulang file tanpa OCR ulang.
- Untuk XTC, preview melewati kuantisasi yang sama dengan file, jadi hasilnya identik. Nomor halaman di bilah status bisa berbeda sampai render penuh selesai.
- Untuk EPUB, live preview mencakup simulasi ukuran huruf device dan efek preset ukuran file pada gambar, dan diberi label "perkiraan".

**CLI:** `--style FILE.json` untuk semua pengaturan, serta flag `--font` dan `--font-size`. GUI menampilkan gaya yang sedang aktif sebagai JSON yang bisa disalin untuk dipakai di CLI.

**Font:**
- Hanya font berlisensi OFL dengan instance statis. File font dan `OFL.txt` disimpan di `src/eco/fonts/`, dengan total ≤ 6 MB.
- Font unggahan disimpan di folder job saja dan ikut terhapus bersama job.

## 9. Kriteria penerimaan

1. *Threat Hunting* (seluruh buku) → EPUB: presisi dan recall teks ≥ 99% dibanding EPUB penerbit.
2. *Bicara itu ada seninya* (scan):
   - akurasi kata halaman 87 ≥ 99% setelah penyambungan pemenggalan;
   - semua judul di halaman 80–92 bebas huruf nyasar;
   - 258 halaman selesai ≤ 15 menit di M3;
   - RAM puncak ≤ 4 GB.
3. Blok kode di halaman uji *Forensic* dan *Malware* barisnya utuh. Listing 11-1 berisi 5 baris, dan blok `icat` berisi 2 baris.
4. Halaman 1 paper ResNet tersusun: judul → penulis → Abstract → isi abstract → Introduction.
5. Rumus (1) dan (2) ResNet muncul sebagai gambar di EPUB.
6. *Practical Malware Analysis* (802 halaman) selesai tanpa RAM puncak melebihi ~4 GB.
7. Output untuk device X4:
   - tanpa progressive JPEG;
   - tanpa gambar lebih besar dari 480×800;
   - tanpa font, SVG, WebP, atau GIF;
   - `mimetype` pertama dan STORED;
   - EPUBCheck tanpa error.
8. EPUB penerbit *Threat Hunting* setelah dioptimalkan untuk X4 berukuran ≤ 1 MB.
9. XTC/XTCH bisa dibuka di Xteink dan daftar babnya berfungsi. Ini uji manual oleh pemilik, yang ditunda. Sampai saat itu, nilai bertanda "verifikasi di device" bersifat sementara.
10. Konversi tidak membuka koneksi jaringan (tes).
11. CI hijau di 3 OS. `uv tool install` → `eco setup` → `eco convert` berjalan di mesin bersih untuk ketiga OS (didokumentasikan; minimal satu kali diverifikasi manual per OS).
12. GUI di Chrome, Firefox, dan Safari:
    - alur unggah → unduh berjalan;
    - progres menampilkan tahap dan halaman;
    - "Batalkan" berhenti dalam ≤ 10 dtk;
    - klik temuan membuat kedua panel lompat;
    - "Ubah pengaturan" tidak mengulang OCR;
    - mode jaringan menolak permintaan tanpa token.
13. Membuka repo di Claude Code memunculkan permintaan pasang ponytail dan antislop. `AGENTS.md` cukup bagi agen baru untuk menjalankan tes tanpa bertanya.
14. Live preview XTC memperbarui halaman dalam ≤ 1 dtk untuk bab ≤ 30 halaman (Mac M3). Halaman preview identik piksel demi piksel dengan halaman hasil decode file XTC/XTCH.
15. Setiap pengaturan di tabel §8.18 mengubah output XTC sesuai harapan, dan masing-masing punya tesnya sendiri.

## 10. Risiko dan hal yang belum diketahui

- **Uji di device ditunda.** Batas ukuran bab, dukungan CSS, dan header XTC memakai nilai sementara yang aman sampai pemilik menguji. Belum diketahui juga apakah firmware bawaan X4 Pro/X4 v2 Classic menampilkan gambar EPUB.
- **Dukungan CSS CrossPoint**, misalnya `white-space: pre-wrap` dan tabel, perlu diverifikasi di device. Jika tidak didukung, untuk device Xteink baris kode dipotong keras dengan penanda lanjutan.
- **Pemenggalan kata bahasa Indonesia di Typst** belum pasti didukung. Jika tidak, fitur ini dimatikan untuk `id`.
- **Docling sering berubah.** Mitigasinya: versi dipin, satu adaptor, dan tes acceptance.
- **Kualitas OCR untuk scan yang lebih buruk** belum diketahui. Jika ambang kriteria 2 tidak tercapai, builder mengevaluasi model OCR lain (model RapidOCR yang lebih besar/Latin, atau EasyOCR) dengan sampel ini sebagai patokan.
- **XY-cut** baru terbukti di 1 halaman, jadi perlu fixture tambahan.
- **`uv tool install` dan PyTorch CPU di Linux** perlu dicek apakah sesuai harapan.
- **Format XTC:** ukuran header berbeda antar-fork, jadi perlu verifikasi di device.
- **Ukuran image Docker** (~2–3 GB dengan PyTorch) dan waktu build CI.

## 11. Diserahkan ke builder

- Tata letak modul.
- Framework CLI (argparse, atau typer yang sudah terbawa Docling).
- Nama fungsi dan endpoint.
- Angka-angka penyetelan: ukuran potongan halaman, kualitas JPEG, ambang multi-kolom/halaman-gambar/tabel-lebar, dan batas ukuran bab.
- Detail template Typst dan font OFL yang dipakai.
- Strategi cache CI.
- Kapan tes integrasi dijalankan.
- Detail Dockerfile.

## 12. Catatan keputusan

**Diputuskan pemilik:**
- Tool pribadi untuk e-reader. Input PDF (semua jenis) dan Markdown; output EPUB dan XTC/XTCH.
- Optimizer umum dan Xteink, plus kompresi.
- Lintas platform: Mac, Windows, Linux.
- Docling sebagai mesin PDF (setelah spike).
- Ada CLI **dan** GUI web. Preview menampilkan hasil dan bentuknya di e-reader.
- Tata letak GUI gabungan A+B+C (mockup disetujui).
- Mudah di-install/deploy dan dirawat. Siap kolaborasi untuk orang dan agen di mesin berbeda. Memakai plugin ponytail dan antislop.
- Repo di folder ini dan disiapkan untuk GitHub.
- Ukur dan minta persetujuan sebelum unduhan besar.
- Gaya visual GUI B (netral dan bersih). UI berbahasa Inggris.
- Semua model Xteink didukung dan dipilih pengguna, ditambah target umum.
- Urutan: GUI sebelum XTC.
- Repo publik, lisensi MIT, identitas git noreply khusus repo ini.
- README dua bahasa. Kode, komentar, `AGENTS.md`, dan commit berbahasa Inggris.
- Uji di device dilakukan nanti.
- (2026-11-17) Pengaturan gaya halaman XTC setara xtctool.com + live preview (§8.18).

**Usulan saya (bisa dibatalkan pemilik):**
- Arsitektur Python lokal (§7.1).
- Stack GUI FastAPI + HTML/JS tanpa build (§7.3).
- Typst untuk XTC dan preview.
- Folder buku Markdown sebagai format tengah yang bisa diedit.
- Input EPUB diterima untuk dioptimalkan.
- Tahap perbaikan §8.4, termasuk tetap memakai mode OCR default + pembersih artefak.
- Default device X4, firmware `any`, output EPUB; XTCH sebagai format XTC default.
- Firmware dipindah ke pemilih "View as" di preview dan ke Advanced settings, karena file EPUB-nya sama untuk semua firmware.
- Server hanya bisa diakses dari mesin itu sendiri, dan token wajib di mode jaringan.
- Model diunduh saat pertama dijalankan setelah ukurannya ditampilkan.
- Nama perintah `eco`.
- Dari builder check:
  - urutan rilis M1–M4 dan titik uji di device (§8.0);
  - folder buku: HTML mentah boleh, penanda halaman, berdiri sendiri (§8.5);
  - EPUB → model buku sebatas yang wajar (§8.6);
  - preset `--size` (§8.8);
  - proses pekerja untuk pembatalan (§8.2);
  - kunci jawaban di `samples/ground-truth/` (§8.17);
  - salinan mockup tersanitasi di `docs/design/`.

## 13. Pertanyaan terbuka untuk pemilik

Tidak ada lagi. Semua pertanyaan terjawab pada 2026-11-16 (lihat §12).

## 14. Referensi

Lihat [docs/research/2026-11-16-references.md](../../research/2026-11-16-references.md) dan [docs/research/2026-11-16-spike-pdf-engines.md](../../research/2026-11-16-spike-pdf-engines.md).
