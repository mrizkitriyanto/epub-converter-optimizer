# eco

[English](README.md)

eco mengubah file PDF dan Markdown menjadi EPUB, dan mengoptimalkan file EPUB. Hasilnya disesuaikan untuk e-reader Xteink (X4, X4 Pro, X4 v2 Classic, X3) dan untuk e-reader umum. eco bisa mengalirkan ulang teks, mempertahankan halaman tetap, menjalankan OCR pada PDF hasil pindai, dan memperkecil gambar serta ukuran file.

eco berupa alat baris perintah dengan GUI web yang berjalan di komputer Anda sendiri. Output XTC sedang direncanakan.

## Persyaratan

| | macOS | Windows | Linux |
|---|---|---|---|
| Sistem | 14+, Apple Silicon (Mac Intel tidak didukung) | 10/11, x64 | x64, glibc 2.28+ (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| RAM | 8 GB | 8 GB | 8 GB |
| Disk | sekitar 3 GB | sekitar 3 GB | sekitar 3 GB (dengan PyTorch versi CPU) |
| Unduhan pertama | sekitar 0,8 GB (paket 0,35 GB, model 0,42 GB) | sekitar 0,9 GB | sekitar 1 GB (wajib PyTorch versi CPU) |
| GPU | opsional (GPU Apple dipakai otomatis) | opsional | opsional |

Anda memerlukan [uv](https://docs.astral.sh/uv/). uv memasang Python 3.12 untuk Anda.

Di Windows, pasang [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) sebelum menjalankan `eco setup`. Windows 10/11 yang baru dipasang bisa belum memilikinya; tanpa itu PyTorch, onnxruntime, dan rtree tidak bisa dimuat, sehingga `eco setup` dan setiap konversi PDF gagal dengan galat DLL.

## Pemasangan

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Lalu unduh model AI satu kali. Perintah ini menampilkan ukurannya (sekitar 417 MB) dan meminta persetujuan dulu:

```bash
eco setup
```

## Penggunaan

Ubah satu file atau lebih. EPUB diberi nama seperti `buku.x4.epub` dan ditulis di samping file input, atau ke folder `-o DIR`:

```bash
eco convert buku.pdf
eco convert buku.pdf catatan.md -o out/
eco convert buku.pdf --device x4 --size small --mode reflow --ocr off
```

Opsi `eco convert INPUT...`:

- `-o DIR`: folder output.
- `--device x4|x4-pro|x4-classic|x3|general`: device tujuan.
- `--size small|balanced|best`: preset ukuran file.
- `--mode auto|reflow|pages`: alirkan ulang teks atau pertahankan halaman tetap.
- `--ocr auto|force|off`: OCR untuk halaman hasil pindai.

Ekstrak PDF ke folder buku Markdown yang bisa diedit (`buku.book/`), tanpa membuat EPUB:

```bash
eco extract buku.pdf -o out/
```

## GUI web

```bash
eco web
```

Perintah ini menjalankan server lokal dan membuka `http://127.0.0.1:8000/` di browser Anda. Tambahkan file PDF, Markdown, atau EPUB (sampai 200 file per unggahan), pilih device dan pengaturan, lalu mulai. Kemajuan menampilkan tahap dan halaman, dan Anda bisa membatalkan konversi yang sedang berjalan. Tinjauan menampilkan temuan di samping halaman asli dan pratinjau halaman e-reader. Satu klik pada temuan menggerakkan keduanya. "Change settings" mengubah lagi dengan pengaturan lain; PDF tidak dibaca ulang. Setelah itu unduh EPUB-nya. Semuanya diproses di komputer ini. Halamannya hanya berbahasa Inggris, jadi nama tombol dan label di sini ditulis dalam bahasa Inggris.

Opsi `eco web`:

- `--host ALAMAT`: alamat yang didengarkan. Bawaannya `127.0.0.1`, hanya komputer ini. Lihat "Akses jaringan" di bawah.
- `--port N`: port yang didengarkan (bawaan 8000).
- `--token TOKEN`: token akses, minimal 16 karakter, masing-masing salah satu dari A-Z, a-z, 0-9, `-`, atau `_`. `ECO_TOKEN` berfungsi sama.
- `--max-upload-mb MB`: unggahan terbesar dalam MiB, untuk semua file dalam satu unggahan (bawaan 500).
- `--no-browser`: jangan buka browser. Alamatnya dicetak sebagai `Open: ...`.
- `--data DIR`: folder data untuk model dan job (bawaan: `ECO_DATA` atau folder aplikasi).

Jika model AI belum ada, halaman pertama memintanya (sekitar 417 MB: layout 172 MB, tabel 213 MB, OCR 32 MB). Model baru diunduh setelah Anda mengklik "Download models". "Continue without models" melewati langkah ini: file Markdown, EPUB, dan PDF dengan Layout "Page images" bisa diubah tanpa model.

File hasil konversi disimpan di folder data sebagai job, sehingga halaman bisa menampilkannya sebagai konversi terbaru. Job dihapus setelah 7 hari (diperiksa tiap jam selama server berjalan). Satu `eco web` bisa berjalan per folder data; yang kedua berhenti dengan galat.

### Akses jaringan

Alamat selain `127.0.0.1`, `localhost`, atau `::1` memerlukan token. Tanpa `--token`, eco membuat satu dan mencetaknya:

```bash
eco web --host 0.0.0.0
```

Alamat yang dicetak adalah `http://0.0.0.0:8000/?token=...`. Di device lain, pakai alamat komputer ini sebagai ganti `0.0.0.0`. Permintaan tanpa token mendapat 401. Permintaan pertama dengan `?token=` memasang cookie, dan halaman menghapus token dari bilah alamat. Koneksinya HTTP biasa, jadi pakai hanya di jaringan yang Anda percaya. Beberapa batasan yang perlu diketahui:

- Tautan `?token=` yang dibuka dari situs lain menampilkan 401 satu kali, karena cookie-nya `SameSite=Strict`. Muat ulang halaman, atau tempel tautannya.
- Cookie `eco_token` berlaku untuk host, bukan port. Layanan HTTP lain di host yang sama menerimanya lewat HTTP biasa.
- Halaman menghapus token dari bilah alamat, tetapi alamat pertama bisa tetap ada di riwayat dan pelengkap otomatis browser, serta di baris perintah yang membuka browser.

## Privasi

Konversi tidak pernah memakai jaringan. Hanya `eco setup` dan tombol "Download models" di `eco web` yang mengunduh model, dan hanya setelah Anda setuju. Model hanya dimuat dalam format data (`.safetensors`, `.onnx`, `.npz`); file pickle ditolak. Dependency dikunci dengan hash dan diperiksa ke database kerentanan di CI.

## Lisensi

MIT. Lihat [LICENSE](LICENSE). Untuk kontributor: lihat [CONTRIBUTING.md](CONTRIBUTING.md) dan [AGENTS.md](AGENTS.md).
