# eco

[English](README.md)

eco mengubah file PDF dan Markdown menjadi EPUB, dan mengoptimalkan file EPUB. Hasilnya disesuaikan untuk e-reader Xteink (X4, X4 Pro, X4 v2 Classic, X3) dan untuk e-reader umum. eco bisa mengalirkan ulang teks, mempertahankan halaman tetap, menjalankan OCR pada PDF hasil pindai, dan memperkecil gambar serta ukuran file.

eco berupa alat baris perintah dengan GUI web yang berjalan di komputer Anda sendiri. eco juga membuat file XTC dan XTCH untuk device Xteink yang didukung.

## Persyaratan

| | Windows | macOS | Linux |
|---|---|---|---|
| Paket native | Windows 10/11 x64 | macOS 15+ Apple Silicon | Ubuntu 22.04 x64 atau distribusi yang kompatibel |
| Pemasangan dari sumber | Windows 10/11 x64 | macOS 14+ Apple Silicon | x64, glibc 2.28+ |
| Memori | RAM 8 GB disarankan | RAM 8 GB disarankan | RAM 8 GB disarankan |
| Ruang kosong | Sekitar 3 GB, ditambah ruang untuk file sumber dan hasil | Sekitar 3 GB, ditambah ruang untuk file sumber dan hasil | Sekitar 3 GB, ditambah ruang untuk file sumber dan hasil |

Setiap arsip native sudah memuat eco, Python, Java Temurin portabel, dan EPUBCheck. Anda tidak perlu memasang Python atau Java di sistem. Windows masih memerlukan [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) untuk PyTorch dan pustaka native lainnya. Arsip native dibangun dan diuji pada OS masing-masing; kompatibilitas dengan versi OS yang lebih lama belum dipastikan.

Pengaliran ulang PDF, tabel, dan OCR memerlukan unduhan model satu kali sekitar 417 MB. Markdown, masukan EPUB, dan PDF berupa gambar halaman bisa diproses sebelum model diunduh. Konversi tidak memakai jaringan.

## Pasang paket native

Pilih `eco-<versi>-windows-x64.zip`, `eco-<versi>-macos-arm64.tar.gz`, atau `eco-<versi>-linux-x64.tar.gz` dari [Releases](https://github.com/mrizkitriyanto/epub-converter-optimizer/releases). Sebelum rilis native bertag pertama, unduh `eco-native-<OS>` dari bagian **Artifacts** pada [build tiga OS yang berhasil](https://github.com/mrizkitriyanto/epub-converter-optimizer/actions/runs/44693577065); unduhan itu berupa ZIP yang berisi arsip sesuai OS, dan artifact GitHub memiliki masa berlaku. Biarkan folder `eco` hasil ekstraksi tetap utuh: folder `runtime/` dan `_internal/` diperlukan.

### Windows

Ekstrak ZIP, buka PowerShell di dalam folder `eco` hasil ekstraksi, lalu jalankan:

```powershell
.\eco.exe --help
.\eco.exe web
```

GUI akan terbuka di `http://127.0.0.1:8000/`. Jika model belum ada, GUI akan menawarkan unduhan. Untuk konversi PDF lewat CLI, jalankan `.\eco.exe setup` lebih dulu; perintah ini menampilkan ukuran unduhan dan meminta persetujuan. Untuk mencoba aplikasi tanpa model, unggah file Markdown melalui GUI.

### macOS dan Linux

Ekstrak TAR.GZ, buka terminal dalam folder `eco` hasil ekstraksi, lalu jalankan `./eco --help` dan `./eco web`. Untuk konversi PDF lewat CLI, jalankan `./eco setup` lebih dulu. Arsip macOS belum ditandatangani, sehingga macOS mungkin meminta persetujuan saat pertama kali dibuka.

Setiap EPUB yang dibuat paket native diperiksa dengan EPUBCheck bawaannya sebelum file diserahkan. Kesalahan EPUBCheck menggagalkan konversi file tersebut; peringatan tampil bersama temuan. `runtime/jre/bin/java` dan `runtime/epubcheck/epubcheck.jar` adalah bagian dari eco dan tidak perlu dipasang terpisah.

Untuk memperbarui, ekstrak arsip baru ke folder baru. Model, font, gaya tersimpan, dan job GUI berada di folder data pengguna kecuali Anda memilih `--data` atau `ECO_DATA`, sehingga penggantian folder aplikasi tidak mengganti data tersebut.

## Pasang dari sumber dengan uv

Pasang [uv](https://docs.astral.sh/uv/), yang juga memasang Python 3.12:

```sh
# macOS atau Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
uv tool install git+https://github.com/mrizkitriyanto/epub-converter-optimizer
```

Lalu unduh model AI satu kali. Perintah ini menampilkan ukurannya (sekitar 417 MB) dan meminta persetujuan dulu:

```bash
eco setup
eco web
```

Pemasangan dari sumber menjalankan EPUBCheck bila `ECO_JAVA` dan `ECO_EPUBCHECK_JAR` sama-sama menunjuk ke executable Java dan JAR EPUBCheck. Tanpa keduanya, konversi tetap berjalan tetapi pemeriksaan EPUBCheck dilewati. Jika hanya satu disetel, eco menampilkan galat. Untuk memperbarui, jalankan `uv tool upgrade eco`; untuk menghapus, jalankan `uv tool uninstall eco`. Lihat [pemeriksaan pemasangan](docs/install-check.md) untuk daftar verifikasi per OS.

## Docker

Setelah rilis pertama terbit, jalankan image dengan volume data permanen dan token minimal 16 huruf, angka, `_`, atau `-`:

```sh
docker run -d --name eco -p 8000:8000 -v eco-data:/data -e ECO_TOKEN=replace-with-a-long-secret ghcr.io/mrizkitriyanto/epub-converter-optimizer:latest
```

Buka `http://<server>:8000/?token=<your-secret>`. Kunjungan pertama menyimpan token dalam cookie browser. Image berjalan sebagai uid 10001; folder host yang dipasang pada `/data` harus dapat ditulis oleh uid itu. Jika model belum ada, GUI menawarkan unduhan. Untuk server tanpa internet, jalankan `docker build --build-arg BAKE_MODELS=1 -t eco:offline .` di mesin yang terhubung internet, lalu pindahkan image tersebut.

## Penggunaan

Contoh di bawah memakai perintah `eco`. Dalam arsip native, gunakan `./eco` di macOS/Linux atau `.\eco.exe` di PowerShell. Ubah satu atau beberapa file PDF, Markdown, atau EPUB; Anda juga bisa menyebut folder untuk memproses semua file yang didukung di dalamnya. EPUB diberi nama seperti `buku.x4.epub` dan ditulis di samping file input, atau ke folder `-o DIR`:

```bash
eco convert buku.pdf
eco convert buku.pdf catatan.md -o out/
eco convert buku.pdf --device x4 --size small --mode reflow --ocr off
eco convert buku.pdf --device x4 --format epub,xtc --firmware crosspoint
eco convert buku-lama.epub --device general -o out/
```

Opsi `eco convert INPUT...`:

- `-o DIR`: folder output.
- `--device x4|x4-pro|x4-classic|x3|general`: device tujuan (bawaan: `x4-pro`).
- `--size small|balanced|best`: preset ukuran file.
- `--mode auto|reflow|pages`: alirkan ulang teks atau pertahankan halaman tetap.
- `--ocr auto|force|off`: OCR untuk halaman hasil pindai.
- `--format epub|xtch|xtc`: format keluaran; pisahkan dengan koma, misalnya `epub,xtc`, untuk lebih dari satu format. XTC dan XTCH memerlukan device Xteink yang didukung.
- `--firmware any|stock|crosspoint|crossink`: profil firmware untuk keluaran Xteink.
- `--landscape`: putar halaman Xteink ke arah lanskap.
- `--title`, `--author`, `--lang`: timpa metadata buku; `--lang` menerima kode seperti `en` atau `id`.
- `--data DIR`: folder data; `ECO_DATA` juga dapat menentukannya. Bawaannya folder data pengguna.
- `--focus-mode`: tanam penebalan awal kata dalam XHTML EPUB dan terapkan juga pada XTC. Kata sampai 3 huruf mendapat 1 huruf tebal, kata 4 huruf 2, kata yang lebih panjang 40% (dibulatkan). `--focus-weight 600|700` memilih semibold atau bold (bawaan: 700).

Untuk XTC atau XTCH, gunakan `--style NAMA` untuk gaya halaman tersimpan, atau `--style FILE.json` untuk berkas gaya. `--font NAMA` dan `--font-size N` menimpa pengaturan gaya itu. `eco styles list` menampilkan gaya tersimpan dan penanda default. Tanpa `--style`, konversi memakai gaya default bila tersedia.

Tambahkan font `.ttf` atau `.otf` yang dapat dipakai ulang dengan `eco fonts add FILE...`; lihat dengan `eco fonts list` dan hapus satu keluarga dengan `eco fonts remove FAMILY`. Folder data menyimpan font dan gaya tersimpan.

Ekstrak PDF ke folder buku Markdown yang bisa diedit (`buku.book/`), tanpa membuat EPUB:

```bash
eco extract buku.pdf -o out/
```

## GUI web

```bash
eco web
```

Perintah ini menjalankan server lokal dan membuka `http://127.0.0.1:8000/` di browser Anda. Halamannya punya empat langkah: Select, Convert, Review, dan Export. Semuanya diproses di komputer ini. Halamannya hanya berbahasa Inggris, jadi nama tombol dan label di sini ditulis dalam bahasa Inggris.

- **Select:** tambahkan file PDF, Markdown, atau EPUB (sampai 200 file per unggahan). Setiap PDF menampilkan jumlah halaman, apakah PDF itu digital atau hasil pindai, perkiraan waktu, dan peta berisi satu kotak per halaman yang menandai halaman hasil pindai. Pilih perangkat baca (bawaan Xteink X4 Pro), keluaran EPUB atau XTC, gaya baca yang tersimpan, apakah Focus Mode menyala (tombol **?** di sebelahnya menjelaskannya), dan ukuran file, lalu mulai. Firmware, OCR, layout, judul, penulis, bahasa, dan pustaka Fonts ada di **More settings**. Jika model AI belum ada, sebuah pemberitahuan menawarkan untuk mengunduhnya; Markdown, EPUB, dan PDF yang dijadikan gambar halaman tetap bisa dikonversi tanpa model.
- **Convert:** persentase, sisa waktu dan waktu yang sudah berjalan, satu segmen per tahap, dan untuk PDF sebuah peta halaman yang terisi seiring halaman dibaca. Peringatan muncul begitu ditemukan. Konversi yang sedang berjalan bisa dibatalkan. Review terbuka sendiri saat file pertama selesai.
- **Review:** temuan di samping halaman asli dan pratinjau halaman e-reader; satu klik pada temuan menggerakkan keduanya. Strip di atasnya berisi satu batang per halaman dan menandai halaman yang punya peringatan; klik strip itu atau pakai tombol panah untuk berpindah halaman. Text size, line spacing, side margins, first-line indent, Focus Mode, dan ketebalan bold-nya (semibold atau bold) langsung mengubah pratinjau dan bertanda "changed" sampai Anda memilih **Apply to book**, yang membangun ulang file (PDF tidak dibaca ulang) lalu kembali ke halaman yang sama. Focus Mode ditanam ke dalam EPUB; nilai lain hanya mengubah XTC dan pratinjau, karena di Xteink EPUB mengikuti ukuran huruf, spasi, dan margin dari pengaturan reader. Untuk job yang hanya menghasilkan EPUB, Apply karena itu hanya menghitung perubahan Focus Mode. **Advanced typography** memuat semua nilai gaya, termasuk perataan dan jarak paragraf, dan di sana Anda bisa menyimpan gaya bernama, menjadikannya default, atau menghapusnya. Jika font hilang, eco memakai Literata dan mencatat temuan; karakter yang tidak ada pada font pilihan juga ditampilkan sebagai temuan dan dalam live preview. Setiap file hasil konversi perlu ditinjau sebelum Export.
- **Export:** tombol unduh untuk setiap file, hasil EPUBCheck, dan gaya yang diterapkan.

Focus Mode menebalkan awal kata Latin, Yunani, dan Sirilik langsung dalam teks XHTML EPUB, termasuk jika inputnya EPUB, sehingga tidak perlu pengaturan atau skrip khusus pada e-reader. Kode dan rumus matematika tidak diubah. E-reader masih dapat menimpa format buku.

Opsi `eco web`:

- `--host ALAMAT`: alamat yang didengarkan. Bawaannya `127.0.0.1`, hanya komputer ini. Lihat "Akses jaringan" di bawah.
- `--port N`: port yang didengarkan (bawaan 8000).
- `--token TOKEN`: token akses, minimal 16 karakter, masing-masing salah satu dari A-Z, a-z, 0-9, `-`, atau `_`. `ECO_TOKEN` berfungsi sama.
- `--max-upload-mb MB`: unggahan terbesar dalam MiB, untuk semua file dalam satu unggahan, bilangan bulat di atas 0 (bawaan 500).
- `--no-browser`: jangan buka browser. Alamatnya dicetak sebagai `Open: ...`.
- `--data DIR`: folder data untuk model dan job (bawaan: `ECO_DATA` atau folder data pengguna).

Jika model AI belum ada, halaman pertama memintanya (sekitar 417 MB: layout 172 MB, tabel 213 MB, OCR 32 MB). Model baru diunduh setelah Anda mengklik "Download models". "Continue without models" melewati langkah ini: file Markdown, EPUB, dan PDF dengan Layout "Page images" bisa diubah tanpa model.

File hasil konversi disimpan di folder data sebagai job, sehingga halaman bisa menampilkannya sebagai konversi terbaru. Job dihapus setelah 7 hari (diperiksa tiap jam selama server berjalan). Untuk menghapusnya lebih cepat, beserta unggahan, file EPUB, dan pratinjaunya, buka job itu dan klik "Delete this conversion" di Export, atau di Convert setelah konversi gagal (batalkan dulu konversi yang masih berjalan). Satu `eco web` bisa berjalan per folder data; yang kedua berhenti dengan galat.

### Akses jaringan

Alamat selain `127.0.0.1`, `localhost`, atau `::1` memerlukan token. Tanpa `--token`, eco membuat satu dan mencetaknya:

```bash
eco web --host 0.0.0.0
```

Perintah ini mencetak `Open: http://127.0.0.1:8000/?token=...`, alamat untuk komputer ini, dan satu baris yang mengatakan bahwa device lain memakai alamat jaringan komputer ini sebagai ganti `127.0.0.1` (misalnya `http://192.168.1.20:8000/?token=...`). Permintaan tanpa token mendapat 401. Permintaan pertama dengan `?token=` memasang cookie, dan halaman menghapus token dari bilah alamat. Koneksinya HTTP biasa, jadi pakai hanya di jaringan yang Anda percaya. Beberapa batasan yang perlu diketahui:

- Tautan `?token=` yang dibuka dari situs lain menampilkan 401 satu kali, karena cookie-nya `SameSite=Strict`. Muat ulang halaman, atau tempel tautannya.
- Cookie `eco_token` berlaku untuk host, bukan port. Layanan HTTP lain di host yang sama menerimanya lewat HTTP biasa.
- Halaman menghapus token dari bilah alamat, tetapi alamat pertama bisa tetap ada di riwayat dan pelengkap otomatis browser, serta di baris perintah yang membuka browser.

## Privasi

Konversi tidak pernah memakai jaringan. Hanya `eco setup` dan tombol "Download models" di `eco web` yang mengunduh model, dan hanya setelah Anda setuju. Model hanya dimuat dalam format data (`.safetensors`, `.onnx`, `.npz`); file pickle ditolak. Dependency dikunci dengan hash dan diperiksa ke database kerentanan di CI.

## Jika ada masalah

- **PDF meminta model:** jalankan `eco setup` atau klik **Download models** di GUI. Masukan Markdown dan EPUB bisa diproses tanpa model. PDF sebagai gambar halaman tersedia melalui GUI tanpa model.
- **Windows melaporkan DLL hilang:** pasang Visual C++ Redistributable x64 yang ditautkan di [Persyaratan](#persyaratan), lalu buka eco lagi.
- **EPUBCheck atau Java tidak ditemukan:** ekstrak ulang seluruh arsip native. Executable membutuhkan folder `runtime/` di sebelahnya; memindahkan `eco.exe` atau `eco` saja membuat validasi gagal.
- **Port 8000 sedang dipakai:** jalankan `eco web --port 8765` dan buka `http://127.0.0.1:8765/`.
- **Konversi native gagal saat EPUBCheck:** EPUB yang tidak valid tidak diserahkan. Lihat pesan galat atau peringatan dari eco, coba mode konversi lain, atau laporkan file sumber dan pesannya melalui issue. Pemasangan dari sumber hanya menjalankan EPUBCheck bila `ECO_JAVA` dan `ECO_EPUBCHECK_JAR` sama-sama disetel.

Untuk pemeriksaan pemasangan lengkap, termasuk konversi PDF dan GUI pada tiap OS, ikuti [docs/install-check.md](docs/install-check.md).

## Lisensi

MIT. Lihat [LICENSE](LICENSE). Untuk kontributor: lihat [CONTRIBUTING.md](CONTRIBUTING.md) dan [AGENTS.md](AGENTS.md).
