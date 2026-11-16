# Spike: Docling vs Marker (2026-11-16)

Uji cepat sekali pakai untuk memilih mesin PDF. Kode spike tidak disimpan di repo (throwaway). Dokumen ini mencatat cara uji dan hasilnya.

## Setup

- Mesin: MacBook Apple M3, 24 GB RAM, macOS 26.6.2. Python 3.12 (uv).
- Versi: Docling 2.150.1, Marker 2.2.0 (mode `fast`), PyTorch 2.15.0, onnxruntime 1.32.0 (Docling) / 1.23.2 (Marker). OCR Docling: RapidOCR (PP-OCRv6 small).
- Input: 13 halaman per dokumen, dipotong dari sampel pemilik + 1 paper publik:

| Kode | Sumber | Jenis |
|---|---|---|
| `threathunt` | Foundations of Threat Hunting, hal. 78–90 | PDF digital (InDesign), ada halaman kosong (hal. 10 subset) |
| `forensic` | Practical Forensic Imaging, hal. 105–117 | PDF digital (LaTeX), perintah shell |
| `malware` | Practical Malware Analysis, hal. 262–274 | PDF digital, listing assembly, diagram, halaman kosong, CropBox bergeser 54×63 pt |
| `scan-id` | Bicara itu ada seninya (Oh Su Hyang), hal. 80–92 | Hasil scan tanpa lapisan teks, bahasa Indonesia |
| `paper-2col` | arXiv 1512.03385v1 (ResNet), hal. 1–4 | Paper 2 kolom dengan rumus |

- Uji dijalankan dengan internet diblokir (`sandbox-exec ... (deny network-outbound (remote ip))`, `HF_HUB_OFFLINE=1`).
- Kunci jawaban:
  - `threathunt`: teks EPUB resmi penerbit. Metrik: presisi = porsi kata output yang cocok berurutan dengan EPUB, recall = porsi kata EPUB pada rentang yang tercakup.
  - `scan-id`: transkripsi manual halaman 87 (cetak hal. 69). Metrik: porsi kata transkripsi yang ditemukan berurutan.

## Hasil

| | Docling | Marker |
|---|---|---|
| `threathunt` vs EPUB | presisi 99,4%, recall 99,7% | presisi 99,4%, recall 99,7% |
| `scan-id` hal. 87 | 99,0% (2 kata salah, keduanya pemenggalan kata) | 100% |
| Halaman kosong | aman | crash: `TypeError: 'NoneType' object is not iterable` di `processors/sectionheader.py` (bug Marker 2.2.0) |
| Blok kode | terdeteksi sebagai kode, tapi baris digabung jadi satu baris | tidak ada blok kode; listing jadi tabel, perintah shell jadi paragraf |
| Gambar/diagram | diekstrak (7 gambar) | tidak diekstrak; teks di dalam grafik bocor ke isi |
| Rumus (paper) | `<!-- formula-not-decoded -->` | LaTeX benar |
| Urutan baca 2 kolom | salah di hal. 1 (kolom kanan sebelum Abstract) | benar, tapi nama penulis jadi judul bagian dan ada sampah teks |
| Header/footer, nomor halaman | dibuang | dibuang |
| Paragraf terpotong pergantian halaman (scan) | disambung | tidak disambung |
| Judul bagian di scan | ada huruf nyasar ("Fungsi iPositif f Rayuan") | bersih |
| Waktu per 13 halaman | 8–10 dtk; scan 27 dtk | 4–5 dtk; scan 5 dtk |
| RAM puncak | 1,2–1,6 GB; scan 3,2 GB | 1,1–1,2 GB |
| Model | ~570 MB | ~42 MB |
| Lisensi | MIT | kode Apache-2.0; bobot model OpenRAIL-M (gratis personal/riset/startup < $5M) |

Keputusan: **Docling** (disetujui pemilik), karena kode dan gambar penting untuk buku teknis, dan kelemahannya bisa ditutup tanpa model tambahan (lihat di bawah).

## Eksperimen perbaikan (semua berhasil kecuali dicatat)

1. **Kode diambil ulang dari lapisan teks PDF.** Lokasi blok kode (`prov.bbox`, origin BOTTOMLEFT, relatif ke CropBox) dipakai untuk `pypdfium2 PdfTextPage.get_text_bounded()`. Baris kembali utuh, misalnya listing GINA 5 baris dan 2 perintah `icat`. **Wajib menambahkan offset CropBox** (`page.get_cropbox()[:2]`). Tanpa offset itu, hasil di buku Malware meleset ke area lain. Spasi perataan kolom ikut menyusut jadi satu spasi, jadi perlu direkonstruksi dari posisi karakter.
2. **Rumus dipotong jadi gambar.** Item `formula` di-render dari halaman PDF pada skala 3 (~216 dpi), grayscale, dengan padding 4 pt. Rumus (1) dan (2) ResNet terpotong rapi lengkap dengan nomornya, lebar ~520 px.
3. **Urutan baca XY-cut.** Bbox item per halaman diurutkan dengan XY-cut rekursif: potong pita horizontal dulu (celah ≥ 6 pt), lalu kolom. Hasil hal. 1 paper menjadi judul → penulis → Abstract → Introduction. Item `page_header` (stempel arXiv) adalah furnitur dan dibuang.
4. **OCR mode `full_page`** (`--ocr-mode full_page`). Semua judul di scan menjadi bersih, waktu turun ke 18 dtk, dan RAM puncak 2,3 GB. Tapi satu kalimat bercetak miring di hal. 87 rusak ("ycern a ( -sr r ne (d ri)"), sehingga akurasi hal. 87 turun ke 95%. **Tidak dipakai mentah.**

## Instalasi, jaringan, keamanan

- Docling **tidak** menarik `onnxruntime` secara otomatis. Akibatnya RapidOCR gagal dengan `ImportError: onnxruntime is not installed`, jadi dependency ini harus eksplisit.
- Docling CLI kini memakai subperintah `docling convert`. API Docling sering berubah, jadi versinya perlu dipin.
- Download paket (Mac, kedua mesin): ~310 MB. Windows ~370 MB. Linux ~3,3 GB dengan PyTorch default (CUDA) atau ~0,5 GB dengan indeks CPU.
- Versi OS minimum dari wheel: Docling butuh macOS 14 di Apple Silicon (`docling-parse`), Marker cukup macOS 13. Linux butuh glibc 2.28. Mac Intel tidak didukung (`docling-parse` tidak punya wheel Intel, dan Marker terbaru butuh PyTorch yang tidak tersedia untuk Intel).
- Jaringan pemilik: koneksi IPv6/NAT64 sesekali direset saat TLS handshake. Pengunduh `hf-xet` (Rust) tidak bisa dipaksa ke IPv4, sehingga macet total. Solusinya: `HF_HUB_DISABLE_XET=1`, paksa IPv4, `HF_HUB_DOWNLOAD_TIMEOUT=20`, lalu coba ulang sambil melanjutkan file `.incomplete`. Kecepatan Hugging Face 125–370 KB/s di satu lokasi dan ~1,4 MB/s di lokasi lain, sementara PyPI 5–10 MB/s.
- OSV (`api.osv.dev/v1/querybatch`): 137 paket, tidak ada yang berbahaya. Setelah torch dinaikkan ke ≥2.13 dan setuptools ke ≥84.1, kerentanannya 0.
- Format model yang terunduh hanya `.safetensors`, `.onnx`, dan `.npz`. Tidak ada pickle (`.pt`, `.bin`, `.pkl`).

## Ukuran EPUB

EPUB penerbit *Foundations of Threat Hunting* berukuran 5,29 MB:

| Isi | Ukuran (zip) | Catatan |
|---|---|---|
| Gambar (26) | 4,2 MB | 25 lebih besar dari 480×800, 2 progressive JPEG |
| Font OTF (10) | 0,93 MB | |
| XHTML | 0,17 MB | |

Estimasi setelah optimasi Xteink: **~0,77 MB (−85%)**. Caranya: gambar abu-abu, dimuat ke 480×800, JPEG baseline q80, font dibuang, deflate level 9.
