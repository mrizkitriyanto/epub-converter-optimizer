# eco

[English](README.md)

eco mengubah file PDF dan Markdown menjadi EPUB. Hasilnya disesuaikan untuk e-reader Xteink (X4, X4 Pro, X4 v2 Classic, X3) dan untuk e-reader umum. eco bisa mengalirkan ulang teks, mempertahankan halaman tetap, menjalankan OCR pada PDF hasil pindai, dan memperkecil gambar serta ukuran file.

Saat ini eco berupa alat baris perintah. GUI web dan output XTC sedang direncanakan.

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

## Privasi

Konversi tidak pernah memakai jaringan. Hanya `eco setup` yang mengunduh model, dan hanya setelah meminta persetujuan. Model hanya dimuat dalam format data (`.safetensors`, `.onnx`, `.npz`); file pickle ditolak. Dependency dikunci dengan hash dan diperiksa ke database kerentanan di CI.

## Lisensi

MIT. Lihat [LICENSE](LICENSE). Untuk kontributor: lihat [CONTRIBUTING.md](CONTRIBUTING.md) dan [AGENTS.md](AGENTS.md).
